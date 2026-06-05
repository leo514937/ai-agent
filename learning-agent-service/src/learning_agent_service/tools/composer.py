from .orchestrator_components import *  # noqa: F401,F403

@dataclass
class AnswerComposer:
    llm_answerer: Callable[[AnswerComposeRequest], Mapping[str, Any] | str] | None = None
    max_citations: int = 4

    def compose(self, request: AnswerComposeRequest) -> AnswerComposeResult:
        if request.allow_direct_response:
            routing = request.routing_decision
            if routing is not None and str(routing.required_action).strip().lower() == "clarify":
                answer_text = self._compose_clarify_response(request, routing)
            elif str(request.direct_response_kind or "").strip().lower() == "conversation_recap":
                answer_text = self._compose_conversation_recap_response(request)
            else:
                answer_text = compose_direct_response_text(
                    request.raw_query,
                    request.direct_response_kind,
                )
            confidence = 0.24 if (routing is not None and routing.required_action == "clarify") else 0.82
            return self._build_result(request, answer_text, confidence, already_streamed=False)

        routing = request.routing_decision
        rag_result = request.rag_result
        evidence_status = self._evidence_status(rag_result)
        evidence_quality = request.evidence_quality
        response_mode = str(
            request.final_response_mode
            or getattr(evidence_quality, "response_mode", "")
            or ""
        ).strip().lower()
        if response_mode == "ask_clarification":
            answer_text = self._compose_clarify_response(request, routing)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.2, already_streamed=False)
        if response_mode == "partial_grounded" and request.tool_result is None and rag_result is not None:
            answer_text = self._compose_partial_grounded_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.55, already_streamed=False)

        mixed_answer = self._compose_rag_plus_tool_answer(request)
        if mixed_answer is not None:
            confidence = 0.88 if request.tool_result is not None and request.rag_result is not None else 0.62
            return self._build_result(request, mixed_answer, confidence, already_streamed=False)

        tool_answer = self._compose_tool_answer(request)
        if tool_answer is not None:
            confidence = 0.86 if request.tool_result and request.tool_result.extra.get("grounding_source") == "business_evidence" else 0.42
            return self._build_result(request, tool_answer, confidence, already_streamed=False)

        if response_mode == "no_answer":
            answer_text = self._compose_no_answer(request, evidence_quality)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.08, already_streamed=False)
        if response_mode == "weak_answer":
            answer_text = self._compose_weak_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.38, already_streamed=False)

        if (
            self.llm_answerer is not None
            and evidence_status in {"EMPTY", "WEAK"}
            and request.plan_summary is None
            and request.tool_result is None
            and request.memory_injection_plan is None
            and not response_mode
        ):
            answer, already_streamed = self._compose_open_answer(request)
            if answer:
                confidence = 0.74 if evidence_status == "EMPTY" else 0.62
                return self._build_result(request, answer, confidence, already_streamed=already_streamed)
        if evidence_status == "EMPTY":
            action = str(getattr(routing, "required_action", "") or "").strip().lower()
            if action == "rag_plus_tool" or (request.tool_result is not None and request.tool_result.status == ToolExecutionStatus.SUCCESS):
                mixed_answer = self._compose_rag_plus_tool_answer(request)
                if mixed_answer is not None:
                    return self._build_result(request, mixed_answer, 0.62, already_streamed=False)
                tool_answer = self._compose_tool_answer(request)
                if tool_answer is not None:
                    return self._build_result(request, tool_answer, 0.42, already_streamed=False)
                fallback_ans = "我这边暂时没有查到这家店的详细评价依据或可用券信息。你可以放宽筛选范围，我继续帮你找。"
                return self._build_result(request, fallback_ans, 0.1, already_streamed=False)

            if self.llm_answerer is None:
                answer_text = self._compose_weak_answer(request)
            else:
                answer_text = "关于这部分业务数据，我暂时没有查到相关依据。要不我们先聊点别的？我知道很多好吃的店铺和省钱优惠券哦～ [Code: RAG_EMPTY_REFUSED]"
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.05, already_streamed=False)

        if evidence_status == "OK":
            answer, already_streamed = self._compose_grounded_answer(request)
            if not answer:
                answer = self._grounded_fallback(request)
                already_streamed = False
            return self._build_result(
                request,
                answer,
                0.9 if self.llm_answerer is not None else 0.84,
                already_streamed=already_streamed,
            )

        answer = self._compose_weak_answer(request)
        return self._build_result(request, answer, 0.58, already_streamed=False)

    def _compose_open_answer(self, request: AnswerComposeRequest) -> tuple[str | None, bool]:
        payload = None
        already_streamed = False
        if self.llm_answerer is not None:
            try:
                stream_relay = _StreamEventRelay(request.stream_event_sink)
                request_with_relay = request.model_copy(update={"stream_event_sink": stream_relay})
                payload = self.llm_answerer(request_with_relay)
                already_streamed = stream_relay.count > 0
            except Exception:
                payload = None
        answer_text = self._extract_answer_text(payload)
        if not answer_text:
            return None, already_streamed
        return self._append_auxiliary_sections(request, answer_text, include_auxiliary=False), already_streamed

    def _compose_grounded_answer(self, request: AnswerComposeRequest) -> tuple[str, bool]:
        payload = None
        already_streamed = False
        if self.llm_answerer is not None:
            try:
                stream_relay = _StreamEventRelay(request.stream_event_sink)
                request_with_relay = request.model_copy(update={"stream_event_sink": stream_relay})
                payload = self.llm_answerer(request_with_relay)
                already_streamed = stream_relay.count > 0
            except Exception:
                payload = None
        answer_text = self._extract_answer_text(payload)
        if not answer_text:
            answer_text = self._grounded_fallback(request)
        citations = self._collect_citations(request)
        if citations:
            answer_text = self._ensure_citations(answer_text, citations)
        return self._append_auxiliary_sections(request, answer_text, include_auxiliary=True), already_streamed

    def _build_result(
        self,
        request: AnswerComposeRequest,
        answer_text: str,
        confidence: float,
        *,
        already_streamed: bool = False,
    ) -> AnswerComposeResult:
        normalized = str(answer_text or "").strip()

        if normalized and not already_streamed:
            self._emit_fallback_answer_stream(request, normalized)
        return AnswerComposeResult(answer_text=normalized, confidence=confidence)

    def _emit_fallback_answer_stream(self, request: AnswerComposeRequest, answer_text: str) -> None:
        stream_sink = request.stream_event_sink
        if stream_sink is None:
            return

        meta = dict(request.stream_event_meta or {})
        chunks = self._chunk_answer_text(answer_text)
        if not chunks:
            return

        accumulated = []
        for chunk in chunks:
            chunk = str(chunk or "")
            if not chunk.strip():
                continue
            accumulated.append(chunk)
            envelope = SseEnvelope(
                event_type="delta",
                trace_id=str(meta.get("trace_id") or ""),
                session_id=str(meta.get("session_id") or ""),
                turn_id=str(meta.get("turn_id") or ""),
                timestamp=datetime.now(UTC),
                workflow_version=str(meta.get("workflow_version") or "learn-agent/v1"),
                payload={
                    "delta": chunk,
                    "answer_text": "".join(accumulated),
                    "current_stage": str(meta.get("current_stage") or "compose"),
                    "stage_status": str(meta.get("stage_status") or "streaming"),
                    "route_decision": meta.get("route_decision"),
                    "route_reason": meta.get("route_reason"),
                },
            )
            if callable(stream_sink):
                stream_sink(envelope)
                time.sleep(0.05)
                continue
            put = getattr(stream_sink, "put", None)
            if callable(put):
                put(envelope)
                time.sleep(0.05)

    @staticmethod
    def _chunk_answer_text(answer_text: str) -> list[str]:
        text = str(answer_text or "").strip()
        if not text:
            return []

        pieces = [piece for piece in re.split(r"(?<=[。！？!?；;\n])", text) if piece]
        if len(pieces) <= 1:
            size = 24
            return [text[i : i + size] for i in range(0, len(text), size)]

        chunks: list[str] = []
        for piece in pieces:
            if len(piece) <= 24:
                chunks.append(piece)
                continue
            chunks.extend(piece[i : i + 24] for i in range(0, len(piece), 24))
        return chunks

    def _compose_tool_answer(self, request: AnswerComposeRequest) -> str | None:
        tool_result = request.tool_result
        if tool_result is None or not tool_result.tool_name:
            return None
        failure_category = str(tool_result.extra.get("failure_category") or "").strip().lower()
        if failure_category == "no_tool_mapping":
            return (
                "这次我没能把这类本地生活请求稳定映射到具体工具，所以先不继续执行，避免误路由。"
                "你可以补充店名、城市、距离或想比较的对象，我再重新走一次工具链。"
            )
        if failure_category == "approval_required" or tool_result.status == ToolExecutionStatus.PENDING_APPROVAL:
            return (
                "这个操作还处于待确认状态。当前 P0 版本对下单、订座、取消、退款这类写操作只保留能力预留，"
                "暂时不直接代你执行。你可以先告诉我想确认的店铺或订单信息，我先帮你把可查的信息整理清楚。"
            )
        if failure_category == "permission_denied" or tool_result.status == ToolExecutionStatus.REJECTED:
            return "当前无权查看或执行这项操作。你可以先登录、补充校验信息，或确认当前账号是否有对应权限。"
        if failure_category == "timeout":
            return "刚才查询超时了。你可以稍后重试，我也可以先帮你缩小范围再查。"
        if failure_category == "dependency_unavailable":
            return "相关服务暂时不可用，这次还查不到结果。你可以稍后再试。"
        if failure_category == "no_result":
            return self._compose_no_result_answer(tool_result.tool_name, tool_result.normalized_output, request)
        if tool_result.status == ToolExecutionStatus.SUCCESS and tool_result.extra.get("grounding_source") == "business_evidence":
            return self._compose_tool_success_answer(tool_result.tool_name, tool_result.normalized_output, request)
        return None

    def _compose_rag_plus_tool_answer(self, request: AnswerComposeRequest) -> str | None:
        routing = request.routing_decision
        action = str(getattr(routing, "required_action", "") or "").strip().lower()
        if action != "rag_plus_tool":
            return None

        sections: list[str] = []
        coupon_answer = self._compose_tool_answer(request)
        if coupon_answer:
            sections.append(f"券信息：{coupon_answer}")

        environment_answer = self._compose_environment_answer(request)
        if environment_answer:
            sections.append(f"环境评价：{environment_answer}")

        if not sections:
            return None
        return "\n".join(sections)

    def _compose_environment_answer(self, request: AnswerComposeRequest) -> str | None:
        rag_result = request.rag_result
        if rag_result is None:
            return None

        evidence_pack = rag_result.evidence_pack
        items = list(evidence_pack.items if evidence_pack else [])
        evidence_status = self._evidence_status(rag_result)
        if not items:
            if evidence_status == "OK":
                return "评价证据有限，暂时没有足够信息判断环境。"
            return "评价证据有限，暂时不敢硬说环境好坏。"

        joined_text = " ".join(str(item.content or "") for item in items[:4]).strip()
        signals: list[str] = []
        if any(token in joined_text for token in ("安静", "不吵", "静")):
            signals.append("环境偏安静")
        if any(token in joined_text for token in ("包间", "私密", "隔音")):
            signals.append("私密性还可以")
        if any(token in joined_text for token in ("家庭聚餐", "聚餐", "带父母", "带长辈", "约会")):
            signals.append("比较适合家庭聚餐或约会")
        if any(token in joined_text for token in ("口碑", "评价不错", "氛围", "体验不错", "服务不错")):
            signals.append("整体口碑还不错")
        if any(token in joined_text for token in ("吵", "排队", "拥挤")):
            signals.append("高峰期可能会偏吵或偏挤")

        if signals:
            return "从评价看，" + "；".join(signals) + "。"

        snippets: list[str] = []
        for item in items[:2]:
            content = str(item.content or "").strip().replace("\n", " ")
            if not content:
                continue
            if len(content) > 96:
                content = content[:93].rstrip() + "..."
            snippets.append(content)
        if not snippets:
            return "评价证据有限，暂时没有足够信息判断环境。"
        if len(snippets) == 1:
            return f"评价里能看到：{snippets[0]}。"
        return f"评价里能看到：{snippets[0]}；{snippets[1]}。"

    def _compose_clarify_response(self, request: AnswerComposeRequest, routing: Any) -> str:
        question = str(getattr(routing, "clarification_question", "") or "").strip()
        if question:
            return question
        clarification_slot = str(getattr(routing, "clarification_slot", "") or getattr(request.evidence_quality, "clarification_slot", "") or request.clarification_slot or "").strip()
        missing_slots = list(getattr(routing, "missing_slots", None) or request.missing_slots or getattr(request.evidence_quality, "missing_slots", None) or [])
        slot_question = build_clarification_question(
            missing_slots,
            clarification_slot=clarification_slot or None,
            query_text=request.raw_query,
        )
        if slot_question:
            return slot_question
        kind = str(request.direct_response_kind or "").strip().lower()
        if kind:
            return compose_direct_response_text(request.raw_query, kind)
        return compose_direct_response_text(request.raw_query, "low_info")

    def _compose_conversation_recap_response(self, request: AnswerComposeRequest) -> str:
        summary = str(request.history_summary or "").strip()
        meta = dict(request.stream_event_meta or {})
        current_shop = str(meta.get("current_shop") or "").strip()
        if not current_shop and request.answer_contract is not None:
            current_shop = str(request.answer_contract.selected_entity or "").strip()
        if not current_shop and request.entity_join_result is not None:
            current_shop = str(request.entity_join_result.selected_entity or "").strip()
        if current_shop and summary:
            return f"我们刚才主要在聊{current_shop}：{summary}。如果你愿意，我可以继续接着这个话题说。"
        if current_shop:
            return f"我们刚才主要在聊{current_shop}。如果你愿意，我可以继续接着这个话题说。"
        if summary:
            return f"我们刚才主要在聊：{summary}。如果你愿意，我可以继续接着这个话题说。"
        return "我能记住我们刚才的上下文，但这一轮还没沉淀出可回顾的摘要。你可以再问我刚才那家店、刚才的券，或者让我继续接着说。"

    def _compose_partial_grounded_answer(self, request: AnswerComposeRequest) -> str:
        evidence_quality = request.evidence_quality
        covered_facets = list(getattr(evidence_quality, "covered_facets", None) or [])
        missing_facets = list(getattr(evidence_quality, "missing_facets", None) or [])
        slot_notes: list[str] = []
        if covered_facets:
            slot_notes.append(f"已确认：{'、'.join(self._facet_labels(covered_facets[:3]))}")
        if missing_facets:
            slot_notes.append(f"暂未确认：{'、'.join(self._facet_labels(missing_facets[:3]))}")
        intro = "目前只能先给你一个部分判断。"
        if slot_notes:
            intro = f"{intro} {'；'.join(slot_notes)}。"
        body = self._grounded_fallback(request)
        if body.startswith("噢，系统服务出现了一点小状况呢") or "RAG_NO_ANSWER" in body:
            return body
        return self._append_auxiliary_sections(request, f"{intro}\n{body}", include_auxiliary=True)

    def _compose_no_result_answer(self, tool_name: str, payload: Mapping[str, Any], request: AnswerComposeRequest | None = None) -> str:
        data = _tool_data(payload)
        shop_name = str(data.get("shop_name") or "这家店").strip() or "这家店"
        concrete_shop_name = ""
        has_static_vouchers = False
        static_info = ""
        
        if request is not None:
            if request.answer_contract:
                contract_extra = _slot_mapping(getattr(request.answer_contract, "extra", {}))
                candidate_shop_name = _optional_str(contract_extra.get("selected_shop_name") or contract_extra.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.entity_join_result:
                extra_data = _slot_mapping(getattr(request.entity_join_result, "extra", {}))
                candidate_shop_name = _optional_str(extra_data.get("selected_shop_name") or extra_data.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.stream_event_meta:
                meta = _slot_mapping(request.stream_event_meta)
                candidate_shop_name = _optional_str(meta.get("current_shop") or meta.get("selected_shop_name"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
                for ev_item in request.rag_result.evidence_pack.items:
                    meta = _slot_mapping(getattr(ev_item, "metadata", {}))
                    candidate_shop_name = _optional_str(meta.get("shop_name") or meta.get("shopName"))
                    if candidate_shop_name:
                        concrete_shop_name = candidate_shop_name
                        break

            if request.rag_result and request.rag_result.evidence_pack:
                for item in request.rag_result.evidence_pack.items:
                    content = str(item.content or "").strip()
                    meta = getattr(item, "metadata", {}) or {}
                    v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                    pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                    if v_count or pkg_desc:
                        has_static_vouchers = True
                        if v_count:
                            static_info += f"优惠券数量：{v_count}张 "
                        if pkg_desc:
                            static_info += f"套餐说明：{pkg_desc}"
                        break
                    elif "券" in content or "优惠" in content or "套餐" in content:
                        has_static_vouchers = True
                        static_info = "知识库中包含相关优惠或套餐描述"
                        break

        if concrete_shop_name:
            shop_name = concrete_shop_name

        if tool_name == "get_order_status":
            return "我这边还没查到对应的订单信息。你可以补充订单号，或者确认一下是不是查错了门店和订单。"
        if tool_name == "get_coupon_list":
            if has_static_vouchers:
                return f"{shop_name} 实时未查到可用券，可参考券存在（{static_info}）但需以实时接口为准。"
            return f"我这边还没查到 {shop_name} 可用的券。你可以换一家店，或者告诉我想看的店名和区域。"
        if tool_name == "get_shop_detail":
            return "我这边还没定位到你要看的门店。你可以补充店名、区域，或者直接给我店铺 id。"
        if tool_name == "search_restaurants":
            return "我这边暂时没筛到符合条件的门店。你可以放宽预算、距离或口味条件，我继续帮你找。"
        return "我这边还没查到对应结果。你可以补充更具体的对象、范围或条件，我继续帮你查。"

    def _compose_tool_success_answer(self, tool_name: str, payload: Mapping[str, Any], request: AnswerComposeRequest | None = None) -> str:
        data = _tool_data(payload)
        
        concrete_shop_name = ""
        has_static_vouchers = False
        static_info = ""
        
        if request is not None:
            if request.answer_contract:
                contract_extra = _slot_mapping(getattr(request.answer_contract, "extra", {}))
                candidate_shop_name = _optional_str(contract_extra.get("selected_shop_name") or contract_extra.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.entity_join_result:
                extra_data = _slot_mapping(getattr(request.entity_join_result, "extra", {}))
                candidate_shop_name = _optional_str(extra_data.get("selected_shop_name") or extra_data.get("current_shop"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.stream_event_meta:
                meta = _slot_mapping(request.stream_event_meta)
                candidate_shop_name = _optional_str(meta.get("current_shop") or meta.get("selected_shop_name"))
                if candidate_shop_name:
                    concrete_shop_name = candidate_shop_name
            if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
                for ev_item in request.rag_result.evidence_pack.items:
                    meta = _slot_mapping(getattr(ev_item, "metadata", {}))
                    candidate_shop_name = _optional_str(meta.get("shop_name") or meta.get("shopName"))
                    if candidate_shop_name:
                        concrete_shop_name = candidate_shop_name
                        break

            if request.rag_result and request.rag_result.evidence_pack:
                for item in request.rag_result.evidence_pack.items:
                    content = str(item.content or "").strip()
                    meta = getattr(item, "metadata", {}) or {}
                    v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                    pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                    if v_count or pkg_desc:
                        has_static_vouchers = True
                        if v_count:
                            static_info += f"优惠券数量：{v_count}张 "
                        if pkg_desc:
                            static_info += f"套餐说明：{pkg_desc}"
                        break
                    elif "券" in content or "优惠" in content or "套餐" in content:
                        has_static_vouchers = True
                        static_info = "知识库中包含相关优惠或套餐描述"
                        break

        if tool_name == "search_restaurants":
            candidates = list(data.get("candidates") or [])
            names = [str(item.get("name") or "").strip() for item in candidates[:3] if isinstance(item, Mapping)]
            lead = "我先帮你筛到这些更匹配的门店："
            if names:
                lead = f"{lead}{'、'.join(name for name in names if name)}。"
            count = int(data.get('candidate_count') or len(candidates))
            return f"{lead} 当前一共命中 {count} 家，如果你愿意，我可以继续帮你细化到距离、价格或适合的场景。"
        if tool_name == "get_shop_detail":
            shop = _slot_mapping(data.get("shop"))
            shop_name = str(shop.get("name") or "这家店").strip() or "这家店"
            if concrete_shop_name:
                shop_name = concrete_shop_name
            score = shop.get("score")
            avg_price = shop.get("avgPrice") or shop.get("avg_price")
            parts = [f"{shop_name} 的门店信息我查到了"]
            if score not in (None, ""):
                parts.append(f"评分大约 {score}")
            if avg_price not in (None, ""):
                parts.append(f"人均约 {avg_price} 元")
            open_status = _slot_mapping(data.get("open_status"))
            if str(open_status.get("open_status") or "").strip():
                parts.append(f"当前状态是 {open_status.get('open_status')}")
            return "，".join(parts) + "。"
        if tool_name == "get_coupon_list":
            shop_name = str(data.get("shop_name") or "这家店").strip() or "这家店"
            if concrete_shop_name:
                shop_name = concrete_shop_name
            coupons = list(data.get("coupons") or [])
            count = int(data.get("count") or len(coupons) or 0)
            if count <= 0 or not coupons:
                if has_static_vouchers:
                    return f"{shop_name} 实时未查到可用券，可参考券存在（{static_info}）但需以实时接口为准。"
                return f"{shop_name} 目前还没有可用券。你可以换一家店，或者告诉我想看的店名和区域。"
            summaries: list[str] = []
            for coupon in coupons[:3]:
                if not isinstance(coupon, Mapping):
                    continue
                title = str(coupon.get("title") or "").strip()
                pay_value = coupon.get("payValue")
                actual_value = coupon.get("actualValue")
                if title and pay_value not in (None, "") and actual_value not in (None, ""):
                    summaries.append(f"{title}（{pay_value} 元代 {actual_value} 元）")
                elif title:
                    summaries.append(title)
            body = "、".join(summaries) if summaries else "我已经查到可用券"
            return f"{shop_name} 当前能看到这些券：{body}。"
        if tool_name == "get_order_status":
            order = _slot_mapping(data.get("order"))
            order_id = str(order.get("order_id") or order.get("transaction_id") or "").strip()
            status = str(order.get("status") or data.get("status") or "unknown").strip()
            if order_id:
                return f"我查到订单 {order_id} 当前状态是 {status}。"
            return f"我查到这笔订单当前状态是 {status}。"
        if tool_name == "get_distance_eta":
            distance = data.get("distance_km")
            eta = data.get("eta_minutes")
            mode = str(data.get("mode") or "drive")
            return f"按 {mode} 方式估算，距离大约 {distance} 公里，预计 {eta} 分钟左右到。"
        if tool_name == "check_open_status":
            status = str(data.get("open_status") or "unknown")
            return f"我查到这家店当前状态是 {status}。"
        return "我已经根据业务数据查到结果了，如果你愿意，我可以继续往下帮你细化。"

    def _compose_weak_answer(self, request: AnswerComposeRequest) -> str:
        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        items = list(evidence_pack.items if evidence_pack else [])
        snippets = [item.content.strip() for item in items[:2] if item.content.strip()]
        if snippets:
            body = "根据当前知识库里的有限证据，我只能给出谨慎判断：{snippets}。如果你希望我继续，建议补充具体范围、版本或背景。".format(
                snippets="；".join(snippets)
            )
        else:
            body = compose_direct_response_text(request.raw_query, "empty")
        return self._append_auxiliary_sections(request, body, include_auxiliary=False)

    def _compose_no_answer(self, request: AnswerComposeRequest, evidence_quality: EvidenceQualityDecision | None) -> str:
        reason = str(getattr(evidence_quality, "reason", "") or "").strip()
        fallback_reason = str(getattr(evidence_quality, "fallback_reason", "") or "").strip()
        if reason in {"shop_mismatch", "geo_mismatch"}:
            body = "我暂时没有找到足够匹配的依据，没法可靠地直接下结论。你可以补充更具体的店名、区域或目标，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        elif reason == "required_role_missing":
            body = "目前缺少足够关键的证据类型，不能给出可信结论。你可以补充更具体的问题、店名、套餐或评价维度，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        elif fallback_reason:
            body = f"我暂时没有找到足够可靠的依据来回答这个问题。你可以补充更多上下文，我再继续帮你查。 [Code: RAG_NO_ANSWER:{fallback_reason}]"
        else:
            body = "我暂时没有找到足够可靠的依据来回答这个问题。你可以补充更多上下文，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        return self._append_auxiliary_sections(request, body, include_auxiliary=False)

    def _grounded_fallback(self, request: AnswerComposeRequest) -> str:
        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        items = list(evidence_pack.items if evidence_pack else [])
        citations = self._collect_citations(request)
        if not items:
            return self._compose_no_answer(request, request.evidence_quality)
        lead = "根据知识库中的证据，可以得到以下结论："
        bullets: list[str] = []
        for item, _citation in zip(items[: self.max_citations], citations or items, strict=False):
            snippet = item.content.strip().replace("\n", " ")
            if len(snippet) > 140:
                snippet = snippet[:137].rstrip() + "..."
            bullets.append(f"- {snippet}")
        return "\n".join([lead, *bullets])

    def _append_auxiliary_sections(self, request: AnswerComposeRequest, answer: str, *, include_auxiliary: bool) -> str:
        return answer

    @staticmethod
    def _facet_labels(facets: Sequence[str]) -> list[str]:
        labels = {
            "shop_detail": "门店详情",
            "recommendation_reason": "推荐理由",
            "environment": "环境",
            "taste": "口味",
            "service": "服务",
            "scene_fit": "适合场景",
            "coupon": "券",
            "open_status": "营业状态",
            "distance_eta": "距离与时间",
            "price": "价格",
        }
        result: list[str] = []
        for facet in facets:
            key = str(facet or "").strip()
            if not key:
                continue
            result.append(labels.get(key, key))
        return result

    @staticmethod
    def _format_memory_section(title: str, memories: Sequence[Any], *, limit: int) -> str:
        summaries: list[str] = []
        for memory in memories[:limit]:
            summary = getattr(memory, "summary", None) or str(getattr(memory, "content", ""))
            summary = str(summary).strip()
            if summary:
                summaries.append(summary)
        if not summaries:
            return ""
        return f"{title}: {' | '.join(summaries)}"

    def _evidence_status(self, rag_result) -> str:
        if rag_result is None:
            return "EMPTY"
        pack = getattr(rag_result, "evidence_pack", None)
        if pack is None:
            return str(getattr(rag_result, "evidence_status", "EMPTY") or "EMPTY").upper()
        return str(getattr(pack, "evidence_status", getattr(rag_result, "evidence_status", "EMPTY")) or "EMPTY").upper()

    def _collect_citations(self, request: AnswerComposeRequest) -> list[Any]:
        rag_result = request.rag_result
        citations = list(rag_result.citations if rag_result else [])
        if citations:
            return citations[: self.max_citations]
        evidence_pack = rag_result.evidence_pack if rag_result else None
        if evidence_pack is None:
            return []
        collected = []
        for item in evidence_pack.items[: self.max_citations]:
            collected.append(
                {
                    "chunk_id": getattr(item, "citation_chunk_id", None) or item.chunk_id,
                    "document_id": item.document_id,
                    "title": item.metadata.get("title") if isinstance(item.metadata, Mapping) else None,
                }
            )
        return collected

    def _ensure_citations(self, answer_text: str, citations: Sequence[Any]) -> str:
        if any(token in answer_text for token in ("[", "(", "【")):
            return answer_text
        marker_text = " ".join(self._citation_marker(citation) for citation in citations[: self.max_citations])
        if not marker_text:
            return answer_text
        return f"{answer_text}\n\n证据引用：{marker_text}"

    @staticmethod
    def _extract_answer_text(payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, Mapping):
            for key in ("answer_text", "answer", "text", "output", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _citation_marker(citation: Any) -> str:
        if isinstance(citation, Mapping):
            chunk_id = str(citation.get("chunk_id") or citation.get("citation_chunk_id") or "").strip()
            title = str(citation.get("title") or "").strip()
        else:
            chunk_id = str(getattr(citation, "chunk_id", "") or getattr(citation, "citation_chunk_id", "") or "").strip()
            title = str(getattr(citation, "title", "") or "").strip()
        if title:
            return f"[{chunk_id}:{title}]" if chunk_id else f"[{title}]"
        return f"[{chunk_id}]" if chunk_id else ""


@dataclass
class Finalizer:
    settings: Settings

    def finalize(self, *args, **kwargs) -> SseEnvelope | None:
        return None
