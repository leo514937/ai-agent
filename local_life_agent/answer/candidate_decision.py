from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from ..domain.schemas import DecisionPlan

def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})

class CandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_id: str
    shop_name: str
    source: str  # recommendation_search / comparison_targets / reference_recovery
    facts: dict[str, Any] = Field(default_factory=dict)
    unknown_facts: list[str] = Field(default_factory=list)
    failed_facts: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    score: Optional[float] = None
    rank: Optional[int] = None

class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_id: str
    detail: Optional[dict[str, Any]] = None
    coupon: Optional[dict[str, Any]] = None
    open_status: Optional[dict[str, Any]] = None
    distance: Optional[dict[str, Any]] = None

class CandidateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_id: str
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    dimension_winners: Optional[dict[str, list[dict[str, Any]]]] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    score: float
    rank: int

class CandidateDecisionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_type: str  # recommendation / comparison / coupon_decision
    user_goal: str
    based_on_location: str
    candidates: list[CandidateItem] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    dimension_winners: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    final_recommendation: Optional[str] = None
    uncertainty_notes: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    must_mention_unknowns: list[str] = Field(default_factory=list)
    answer_style_hints: list[str] = Field(default_factory=list)

class CandidateEvidenceCollector:
    def collect(self, shop_ids: list[str], tool_results: dict[str, Any]) -> list[CandidateEvidence]:
        evidences: dict[str, CandidateEvidence] = {}
        for sid in shop_ids:
            sid_str = str(sid).strip()
            if not sid_str:
                continue
            evidences[sid_str] = CandidateEvidence(shop_id=sid_str)
            
        for call_id, tr in (tool_results or {}).items():
            tr_dict = _to_dict(tr)
            sid = str(tr_dict.get("shop_id", "")).strip()
            if not sid or sid not in evidences:
                continue
            
            tool_name = tr_dict.get("tool_name")
            if tool_name == "get_shop_detail":
                evidences[sid].detail = tr_dict
            elif tool_name == "get_coupon_list":
                evidences[sid].coupon = tr_dict
            elif tool_name == "check_open_status":
                evidences[sid].open_status = tr_dict
            elif tool_name == "get_distance_eta":
                evidences[sid].distance = tr_dict
                
        return list(evidences.values())

class CandidateEvaluator:
    def evaluate(
        self,
        evidences: list[CandidateEvidence],
        decision_type: str,
        preferences: dict[str, Any],
    ) -> list[CandidateEvaluation]:
        candidates_data: list[dict[str, Any]] = []
        for ev in evidences:
            data = {
                "shop_id": ev.shop_id,
                "shop_name": "",
                "category": "",
                "sub_category": "",
                "tags": [],
                "rating": None,
                "distance_km": None,
                "eta_minutes": None,
                "open_status": "unknown",
                "coupon_status": "unknown",
                "coupon_titles": [],
                "coupon_count": None,
                "detail_failed": False,
            }
            
            # Detail facts
            if ev.detail and ev.detail.get("result_status") == "ok" and ev.detail.get("data"):
                d = ev.detail["data"]
                data["shop_name"] = d.get("shop_name", "")
                data["category"] = d.get("category", "")
                data["sub_category"] = d.get("sub_category", "")
                data["tags"] = d.get("tags", [])
                data["rating"] = d.get("rating")
                data["avg_price"] = d.get("avg_price")
            elif ev.detail and ev.detail.get("result_status") in ("failed", "circuit_open", "error", "backend_unavailable"):
                data["detail_failed"] = True
                
            if not data["shop_name"] and ev.detail and ev.detail.get("data"):
                data["shop_name"] = ev.detail["data"].get("shop_name", "")
            
            # Open status facts
            if ev.open_status:
                o_status = ev.open_status.get("result_status")
                if o_status == "ok" and ev.open_status.get("data"):
                    data["open_status"] = ev.open_status["data"].get("open_status", "unknown")
                    if not data["shop_name"]:
                        data["shop_name"] = ev.open_status["data"].get("shop_name", "")
                else:
                    data["open_status"] = "unknown"
            else:
                data["open_status"] = "unknown"
                
            # Coupon facts
            if ev.coupon:
                c_status = ev.coupon.get("result_status")
                if c_status == "ok" and isinstance(ev.coupon.get("data"), list):
                    titles = [item.get("title", "") for item in ev.coupon["data"] if isinstance(item, dict) and item.get("title")]
                    data["coupon_titles"] = titles
                    data["coupon_count"] = len(titles)
                    data["coupon_status"] = "has_coupon" if titles else "empty"
                elif c_status == "empty":
                    data["coupon_titles"] = []
                    data["coupon_count"] = 0
                    data["coupon_status"] = "empty"
                else:
                    data["coupon_titles"] = []
                    data["coupon_count"] = None
                    data["coupon_status"] = "unknown"
            else:
                data["coupon_titles"] = []
                data["coupon_count"] = None
                data["coupon_status"] = "unknown"
                
            # Distance facts
            if ev.distance:
                d_status = ev.distance.get("result_status")
                if d_status == "ok" and ev.distance.get("data"):
                    data["distance_km"] = ev.distance["data"].get("distance_km")
                    data["eta_minutes"] = ev.distance["data"].get("eta_minutes")
                    if not data["shop_name"]:
                        data["shop_name"] = ev.distance["data"].get("shop_name", "")
                else:
                    data["distance_km"] = None
                    data["eta_minutes"] = None
            else:
                data["distance_km"] = None
                data["eta_minutes"] = None
                
            candidates_data.append(data)

        evaluations: list[CandidateEvaluation] = []
        
        if decision_type == "recommendation":
            from ..planning.ranking_policy import score_candidate
            scored_candidates = []
            for item in candidates_data:
                scored = score_candidate(item, preferences)
                scored_candidates.append(scored)
                
            scored_candidates.sort(
                key=lambda x: (
                    -float(x.get("total_score", 0.0) or 0.0),
                    -float(x.get("rating", 0.0) or 0.0),
                    float(x.get("distance_km", 9999.0) or 9999.0),
                    str(x.get("shop_id", "")),
                )
            )
            
            for idx, item in enumerate(scored_candidates, start=1):
                uncertainty = []
                if item.get("open_status") == "unknown":
                    uncertainty.append(f"{item.get('shop_name') or item.get('shop_id')}营业状态暂无法确认")
                if item.get("coupon_status") == "unknown":
                    uncertainty.append(f"{item.get('shop_name') or item.get('shop_id')}优惠暂无法确认")
                if item.get("distance_km") is None:
                    uncertainty.append(f"{item.get('shop_name') or item.get('shop_id')}距离暂无法确认")
                
                risks = []
                if item.get("detail_failed"):
                    risks.append("detail_failed")
                if item.get("open_status") == "closed":
                    risks.append("shop_closed")
                    
                evaluation = CandidateEvaluation(
                    shop_id=item["shop_id"],
                    dimension_scores={
                        "category_match": float(item.get("component_scores", {}).get("category_match", 0.0)),
                        "open_status": float(item.get("component_scores", {}).get("open_status_score", 0.0)),
                        "distance": float(item.get("component_scores", {}).get("distance_score", 0.0)),
                        "rating": float(item.get("component_scores", {}).get("rating_score", 0.0)),
                        "coupon": float(item.get("component_scores", {}).get("coupon_score", 0.0)),
                        "tag_match": float(item.get("component_scores", {}).get("tag_match_score", 0.0)),
                    },
                    dimension_winners=None,
                    reason_codes=item.get("reason_codes", []),
                    risk_flags=risks,
                    uncertainty_notes=uncertainty,
                    score=float(item.get("total_score", 0.0)),
                    rank=idx
                )
                evaluations.append(evaluation)
                
        else:  # comparison
            comparison_rows = []
            for item in candidates_data:
                score = 0.0
                known = 0
                
                rating = item.get("rating")
                if rating is not None:
                    known += 1
                    score += float(rating) / 5.0
                
                distance_km = item.get("distance_km")
                if distance_km is not None:
                    known += 1
                    score += max(0.0, 1.0 - min(float(distance_km), 10.0) / 10.0)
                    
                open_status = str(item.get("open_status", "")).lower()
                if open_status in ("open", "closed"):
                    known += 1
                    score += 1.0 if open_status == "open" else 0.0
                    
                coupon_count = item.get("coupon_count")
                if coupon_count is not None:
                    known += 1
                    score += 1.0 if coupon_count > 0 else 0.0
                    
                overall_score = (score / known) if known > 0 else 0.0
                comparison_rows.append({
                    **item,
                    "overall_score": overall_score,
                    "known_dimensions": known,
                })
                
            comparison_rows.sort(
                key=lambda x: (
                    -float(x.get("overall_score", 0.0)),
                    -float(x.get("rating") or 0.0) if x.get("rating") is not None else 0.0,
                    float(x.get("distance_km") or 9999.0),
                    str(x.get("shop_id", "")),
                )
            )
            
            dimension_winners = {}
            
            # rating winner
            known_ratings = [r for r in comparison_rows if r.get("rating") is not None]
            if len(known_ratings) >= 2:
                best_rating = max(float(r["rating"]) for r in known_ratings)
                dimension_winners["rating"] = [
                    {"shop_id": r["shop_id"], "shop_name": r["shop_name"] or r["shop_id"], "value": r["rating"]}
                    for r in known_ratings if float(r["rating"]) == best_rating
                ]
                
            # distance winner
            known_distances = [r for r in comparison_rows if r.get("distance_km") is not None]
            if len(known_distances) >= 2:
                best_dist = min(float(r["distance_km"]) for r in known_distances)
                dimension_winners["distance"] = [
                    {"shop_id": r["shop_id"], "shop_name": r["shop_name"] or r["shop_id"], "value": r["distance_km"]}
                    for r in known_distances if float(r["distance_km"]) == best_dist
                ]
                
            # open status winner
            open_shops = [r for r in comparison_rows if str(r.get("open_status")).lower() == "open"]
            known_open = [r for r in comparison_rows if str(r.get("open_status")).lower() in ("open", "closed")]
            if len(known_open) >= 2 and open_shops:
                dimension_winners["open_status"] = [
                    {"shop_id": r["shop_id"], "shop_name": r["shop_name"] or r["shop_id"], "value": "open"}
                    for r in open_shops
                ]
                
            # coupon winner
            coupon_shops = [r for r in comparison_rows if r.get("coupon_status") == "has_coupon"]
            known_coupon = [r for r in comparison_rows if r.get("coupon_status") in ("has_coupon", "empty")]
            if len(known_coupon) >= 2 and coupon_shops:
                dimension_winners["coupon"] = [
                    {"shop_id": r["shop_id"], "shop_name": r["shop_name"] or r["shop_id"], "value": len(r.get("coupon_titles", []))}
                    for r in coupon_shops
                ]
                
            for idx, item in enumerate(comparison_rows, start=1):
                uncertainty = []
                if item.get("open_status") == "unknown":
                    uncertainty.append(f"{item.get('shop_name') or item.get('shop_id')}营业状态暂无法确认")
                if item.get("coupon_status") == "unknown":
                    uncertainty.append(f"{item.get('shop_name') or item.get('shop_id')}优惠暂无法确认")
                if item.get("distance_km") is None:
                    uncertainty.append(f"{item.get('shop_name') or item.get('shop_id')}距离暂无法确认")
                    
                evaluations.append(
                    CandidateEvaluation(
                        shop_id=item["shop_id"],
                        dimension_scores={
                            "rating": float(item["rating"]) if item.get("rating") is not None else 0.0,
                            "distance": float(item["distance_km"]) if item.get("distance_km") is not None else 0.0,
                            "overall_score": float(item["overall_score"]),
                        },
                        dimension_winners=dimension_winners,
                        reason_codes=[],
                        risk_flags=[],
                        uncertainty_notes=uncertainty,
                        score=float(item["overall_score"]),
                        rank=idx
                    )
                )
                
        return evaluations

def build_candidate_decision_plan(
    decision_type: str,
    user_goal: str,
    location: str,
    evidences: list[CandidateEvidence],
    evaluations: list[CandidateEvaluation],
    forbidden_claims: list[str],
    must_mention_unknowns: list[str] | None = None,
) -> CandidateDecisionPlan:
    candidates = []
    ranking = []
    
    sorted_evaluations = sorted(evaluations, key=lambda x: x.rank)
    evidence_by_shop_id = {ev.shop_id: ev for ev in evidences}
    
    dim_winners = {}
    if sorted_evaluations:
        dim_winners = sorted_evaluations[0].dimension_winners or {}
        
    uncertainty_notes = []
    seen_uncertainty = set()
    for ev in sorted_evaluations:
        for note in ev.uncertainty_notes:
            if note not in seen_uncertainty:
                seen_uncertainty.add(note)
                uncertainty_notes.append(note)
                
    for ev_val in sorted_evaluations:
        sid = ev_val.shop_id
        ranking.append(sid)
        evidence = evidence_by_shop_id.get(sid)
        
        facts = {}
        unknown_facts = []
        failed_facts = []
        
        if evidence:
            # detail
            if evidence.detail and evidence.detail.get("result_status") == "ok" and evidence.detail.get("data"):
                d = evidence.detail["data"]
                facts["shop_name"] = d.get("shop_name", "")
                facts["rating"] = d.get("rating")
                facts["avg_price"] = d.get("avg_price")
                facts["category"] = d.get("category", "")
                facts["tags"] = d.get("tags", [])
            else:
                unknown_facts.append("detail")
                if evidence.detail and evidence.detail.get("result_status") in ("failed", "circuit_open", "error", "backend_unavailable"):
                    failed_facts.append("detail")
                    
            # open_status
            if evidence.open_status and evidence.open_status.get("result_status") == "ok" and evidence.open_status.get("data"):
                facts["open_status"] = evidence.open_status["data"].get("open_status", "unknown")
            else:
                unknown_facts.append("open_status")
                if evidence.open_status and evidence.open_status.get("result_status") in ("failed", "circuit_open", "error", "backend_unavailable"):
                    failed_facts.append("open_status")
                    
            # coupon
            if evidence.coupon and evidence.coupon.get("result_status") == "ok" and isinstance(evidence.coupon.get("data"), list):
                facts["coupon_status"] = "has_coupon" if evidence.coupon["data"] else "empty"
                facts["coupon_titles"] = [item.get("title", "") for item in evidence.coupon["data"] if isinstance(item, dict) and item.get("title")]
            elif evidence.coupon and evidence.coupon.get("result_status") == "empty":
                facts["coupon_status"] = "empty"
                facts["coupon_titles"] = []
            else:
                unknown_facts.append("coupon")
                if evidence.coupon and evidence.coupon.get("result_status") in ("failed", "circuit_open", "error", "backend_unavailable"):
                    failed_facts.append("coupon")
                    
            # distance
            if evidence.distance and evidence.distance.get("result_status") == "ok" and evidence.distance.get("data"):
                facts["distance_km"] = evidence.distance["data"].get("distance_km")
                facts["eta_minutes"] = evidence.distance["data"].get("eta_minutes")
            else:
                unknown_facts.append("distance")
                if evidence.distance and evidence.distance.get("result_status") in ("failed", "circuit_open", "error", "backend_unavailable"):
                    failed_facts.append("distance")
                    
        shop_name = facts.get("shop_name", "")
        if not shop_name and evidence:
            for item in (evidence.detail, evidence.open_status, evidence.distance):
                if item and item.get("data") and item["data"].get("shop_name"):
                    shop_name = item["data"]["shop_name"]
                    break
        if not shop_name:
            shop_name = sid
            
        candidate_item = CandidateItem(
            shop_id=sid,
            shop_name=shop_name,
            source="recommendation_search" if decision_type == "recommendation" else "comparison_targets",
            facts=facts,
            unknown_facts=unknown_facts,
            failed_facts=failed_facts,
            reason_codes=ev_val.reason_codes,
            score=ev_val.score,
            rank=ev_val.rank
        )
        candidates.append(candidate_item)
        
    final_reco = None
    if decision_type == "recommendation" and candidates:
        final_reco = candidates[0].shop_name
    elif decision_type == "comparison" and candidates:
        if len(candidates) >= 2 and candidates[0].score != candidates[1].score:
            final_reco = candidates[0].shop_name
        elif len(candidates) == 1:
            final_reco = candidates[0].shop_name
            
    plan = CandidateDecisionPlan(
        decision_type=decision_type,
        user_goal=user_goal,
        based_on_location=location,
        candidates=candidates,
        ranking=ranking,
        dimension_winners=dim_winners,
        final_recommendation=final_reco,
        uncertainty_notes=uncertainty_notes,
        forbidden_claims=forbidden_claims,
        must_mention_unknowns=must_mention_unknowns or [],
        answer_style_hints=[]
    )
    return plan

def map_candidate_decision_plan_to_decision_plan(plan: CandidateDecisionPlan) -> DecisionPlan:
    selected_targets = []
    overall_ranking = []
    sorted_candidates = sorted(
        plan.candidates,
        key=lambda candidate: (
            candidate.rank if candidate.rank is not None else 9999,
            -(candidate.score or 0.0),
            candidate.shop_name,
            candidate.shop_id,
        ),
    )
    
    for candidate in sorted_candidates:
        row_dict = {
            "shop_id": candidate.shop_id,
            "shop_name": candidate.shop_name,
            "source": candidate.source,
            "category": candidate.facts.get("category", ""),
            "tags": candidate.facts.get("tags", []),
            "rating": candidate.facts.get("rating"),
            "avg_price": candidate.facts.get("avg_price"),
            "distance_km": candidate.facts.get("distance_km"),
            "eta_minutes": candidate.facts.get("eta_minutes"),
            "open_status": candidate.facts.get("open_status", "unknown"),
            "coupon_status": candidate.facts.get("coupon_status", "unknown"),
            "coupon_titles": candidate.facts.get("coupon_titles", []),
            "coupon_count": len(candidate.facts.get("coupon_titles", [])) if candidate.facts.get("coupon_status") == "has_coupon" else (0 if candidate.facts.get("coupon_status") == "empty" else None),
            "detail_failed": "detail" in candidate.failed_facts,
            "overall_score": candidate.score,
            "rank": candidate.rank,
            "known_dimensions": 4 - len(candidate.unknown_facts),
            "reason_codes": list(candidate.reason_codes),
            "unknown_facts": list(candidate.unknown_facts),
            "failed_facts": list(candidate.failed_facts),
        }
        selected_targets.append(row_dict)
        overall_ranking.append(row_dict)
        
    main_recommendation = None
    if plan.final_recommendation and selected_targets:
        for target in selected_targets:
            if target["shop_name"] == plan.final_recommendation:
                main_recommendation = target
                break
        if not main_recommendation:
            main_recommendation = selected_targets[0]
            
    best_for = {}
    if plan.decision_type == "comparison":
        dim_labels = {
            "rating": "评分",
            "distance": "距离近",
            "open_status": "营业状态",
            "coupon": "省钱"
        }
        for dim, winners in plan.dimension_winners.items():
            label = dim_labels.get(dim)
            if label and winners:
                for w in winners:
                    best_for[label] = {
                        "shop_id": w.get("shop_id", ""),
                        "shop_name": w.get("shop_name", ""),
                        "reason": f"在{label}维度领先"
                    }
                    
    factual_points = []
    candidate_summaries = []
    for candidate in sorted_candidates:
        facts = []
        sname = candidate.shop_name
        if candidate.facts.get("rating") is not None:
            facts.append(f"评分为 {candidate.facts.get('rating')}")
        if candidate.facts.get("distance_km") is not None:
            dist_str = f"距离为 {candidate.facts.get('distance_km')} 公里"
            if candidate.facts.get("eta_minutes") is not None:
                dist_str += f"，预计时间 {candidate.facts.get('eta_minutes')} 分钟"
            facts.append(dist_str)
        if candidate.facts.get("open_status") == "open":
            facts.append("营业状态为：目前营业中")
        elif candidate.facts.get("open_status") == "closed":
            facts.append("营业状态为：目前已打烊")
        if candidate.facts.get("coupon_status") == "has_coupon":
            titles = candidate.facts.get("coupon_titles", [])
            titles_str = "、".join(titles)
            facts.append(f"有券：{titles_str}")
        elif candidate.facts.get("coupon_status") == "empty":
            facts.append("暂无可用券")
        if facts:
            factual_points.append(f"{sname}：{', '.join(facts)}")
        candidate_summaries.append(
            {
                "shop_id": candidate.shop_id,
                "shop_name": candidate.shop_name,
                "rank": candidate.rank,
                "score": candidate.score,
                "source": candidate.source,
                "reason_codes": list(candidate.reason_codes),
                "facts": dict(candidate.facts),
                "unknown_facts": list(candidate.unknown_facts),
                "failed_facts": list(candidate.failed_facts),
            }
        )
            
    omitted_targets = []
    if plan.must_mention_unknowns:
        for u in plan.must_mention_unknowns:
            omitted_targets.append({"shop_name": str(u)})

    return DecisionPlan(
        answer_type=plan.decision_type,
        selected_targets=selected_targets,
        omitted_targets=omitted_targets,
        main_recommendation=main_recommendation,
        overall_ranking=overall_ranking,
        best_for=best_for,
        factual_points=factual_points,
        uncertainty_notes=plan.uncertainty_notes,
        forbidden_claims=plan.forbidden_claims,
        style_hints=plan.answer_style_hints,
        decision_context={
            "decision_type": plan.decision_type,
            "user_goal": plan.user_goal,
            "based_on_location": plan.based_on_location,
            "final_recommendation": plan.final_recommendation,
        },
        candidate_summaries=candidate_summaries,
        must_mention_unknowns=list(plan.must_mention_unknowns),
    )
