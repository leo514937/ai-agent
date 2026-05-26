package macro

type TopicName string

const DigitalAuthorBizTracing TopicName = "data.twin.knowledge.tracing"
const DigitalAuthorIndexChange TopicName = "data.twin.knowledge.index_upsert"
const CommonTracing TopicName = "data.aisp.common-tracing"
const RecallTracing TopicName = "data.aisp.recall-tracing"

const PrefabWord TopicName = "msg.content-brain.aitab_question_generated"

const ContentPool TopicName = "msg.content-pool-core.pool_action"

const HotCrawler TopicName = "data.crawler-core.content_timeliness_topic"

const DocumentParsing TopicName = "msg.ai-ingress.content_pre_read"

const CrawledWebPage TopicName = "data.aisp_crawled_web_page"

const CrawlerWebPage TopicName = "zhida_crawled_html"

const HotEvent TopicName = "msg.content_brain.hot_event"

const ContentActivity TopicName = "msg.sink.activity.CONTENT_ANALYSE_DONE"

const LastNSearchActivity TopicName = "data.aisp.lastn-search"
