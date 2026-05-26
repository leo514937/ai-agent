module git.in.zhihu.com/zhihu/aisp-core

go 1.24

toolchain go1.24.2

require (
	git.in.zhihu.com/Security-Platform/go-protos v1.0.1
	git.in.zhihu.com/ecosystem-cd/evalsdk v0.0.48
	git.in.zhihu.com/go/base v1.4.19
	git.in.zhihu.com/go/borm v0.2.43
	git.in.zhihu.com/go/box v1.7.2
	git.in.zhihu.com/go/cafe v1.0.7
	git.in.zhihu.com/go/logrus v1.0.2
	git.in.zhihu.com/go/utils v0.2.17
	git.in.zhihu.com/go/ztext v0.1.17
	git.in.zhihu.com/one-rpc-go/grpc-aisp_biz v0.0.130
	git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service v0.0.130
	git.in.zhihu.com/one-rpc-go/grpc-aisp_triton_inference v0.0.43-0.20240511092853-78f12c18f237
	git.in.zhihu.com/one-rpc-go/grpc-antispam-prod-api v0.0.0-20230419102941-8cf4a26a5bbf
	git.in.zhihu.com/one-rpc-go/grpc-model_engine v0.0.7
	git.in.zhihu.com/one-rpc-go/grpc-model_gateway v1.4.30
	git.in.zhihu.com/one-rpc-go/thrift-ai_ingress v0.0.10-0.20250819075154-cdbca7c82690
	git.in.zhihu.com/one-rpc-go/thrift-bidding_xg_tools v2.5.8-0.20250113121216-ba57fd593a2c+incompatible
	git.in.zhihu.com/one-rpc-go/thrift-censor v0.0.0-20231122041119-38e044db3b70
	git.in.zhihu.com/one-rpc-go/thrift-chat_content v0.0.123
	git.in.zhihu.com/one-rpc-go/thrift-comment v0.1.29
	git.in.zhihu.com/one-rpc-go/thrift-content-regulate-core v0.3.6-0.20240403054925-443273d8b387
	git.in.zhihu.com/one-rpc-go/thrift-content_prod v0.0.80
	git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core v0.2.6
	git.in.zhihu.com/one-rpc-go/thrift-metis2 v0.0.17
	git.in.zhihu.com/one-rpc-go/thrift-search_service v1.2.5
	git.in.zhihu.com/one-rpc-go/thrift-search_words v0.5.9-0.20231227030616-fbfa0116add1
	git.in.zhihu.com/one-rpc-go/thrift-tag-core v0.1.43
	git.in.zhihu.com/one-rpc-go/thrift-user_core v0.0.64
	git.in.zhihu.com/one-rpc-go/thrift-user_regulate_core v0.0.43
	git.in.zhihu.com/pb-go/zai-proto v3.2.27-apigogov3+incompatible
	git.in.zhihu.com/pb-go/zsearch-proto v0.0.49
	git.in.zhihu.com/production_backend/pier v1.1.29
	git.in.zhihu.com/thrift-go/crawler_core_thrift v0.0.27
	git.in.zhihu.com/thrift-go/eval_regulate_core_thrift v0.0.4
	git.in.zhihu.com/thrift-go/member_thrift v0.1.37
	git.in.zhihu.com/thrift-go/profiled_thrift v0.5.50
	git.in.zhihu.com/thrift-go/qa_go_thrift v0.1.17
	git.in.zhihu.com/thrift-go/zai_pb_thrift v3.2.3+incompatible
	git.in.zhihu.com/thrift-go/zfav_go_thrift v0.0.33
	git.in.zhihu.com/thrift-go/zhuanlan_thrift v0.5.39
	git.in.zhihu.com/thrift-go/zos_thrift v0.0.9
	git.in.zhihu.com/zhsearch/rucenego/v2 v2.12.0
	git.in.zhihu.com/zrec/zag-driver v1.2.4
	git.in.zhihu.com/zrec/zrec-framework v1.4.3
	git.in.zhihu.com/zrec/zrec-utils v0.0.12
	github.com/Azure/azure-sdk-for-go/sdk/ai/azopenai v0.4.1
	github.com/Azure/azure-sdk-for-go/sdk/azcore v1.17.0
	github.com/Masterminds/squirrel v1.5.4
	github.com/PuerkitoBio/goquery v1.9.2
	github.com/alibabacloud-go/darabonba-openapi/v2 v2.0.10
	github.com/alibabacloud-go/iqs-20241111 v1.1.5
	github.com/alibabacloud-go/openapi-util v0.1.1
	github.com/alibabacloud-go/tea v1.2.2
	github.com/alibabacloud-go/tea-utils/v2 v2.0.7
	github.com/apache/thrift v0.12.0
	github.com/baidubce/bce-sdk-go v0.9.167
	github.com/beltran/gohive v1.3.0
	github.com/cespare/xxhash/v2 v2.2.0
	github.com/colinmarc/hdfs v1.1.3
	github.com/dgrijalva/jwt-go v3.2.0+incompatible
	github.com/expr-lang/expr v1.16.1
	github.com/getsentry/raven-go v0.2.0
	github.com/go-chi/chi v4.1.2+incompatible
	github.com/golang/protobuf v1.5.3
	github.com/google/uuid v1.6.0
	github.com/grpc-ecosystem/grpc-gateway/v2 v2.14.0
	github.com/hashicorp/golang-lru/v2 v2.0.7
	github.com/imjasonmiller/godice v0.1.2
	github.com/imroc/req v0.3.0
	github.com/imroc/req/v3 v3.41.12
	github.com/juju/ratelimit v1.0.2
	github.com/mitchellh/mapstructure v1.4.1
	github.com/mroth/weightedrand v1.0.0
	github.com/olekukonko/tablewriter v0.0.5
	github.com/openai/openai-go/v2 v2.1.1
	github.com/patrickmn/go-cache v2.1.0+incompatible
	github.com/philchia/agollo/v4 v4.1.6-rc.1
	github.com/pkg/errors v0.9.1
	github.com/samber/lo v1.50.0
	github.com/sashabaranov/go-openai v1.18.1
	github.com/spf13/cast v1.7.1
	github.com/stretchr/objx v0.5.2
	github.com/stretchr/testify v1.10.0
	github.com/tealeg/xlsx v1.0.5
	github.com/tidwall/gjson v1.18.0
	github.com/vmihailenco/msgpack/v5 v5.3.5
	github.com/xuri/excelize/v2 v2.8.0
	go.uber.org/ratelimit v0.3.1
	golang.org/x/exp v0.0.0-20230817173708-d852ddb80c63
	google.golang.org/genproto/googleapis/api v0.0.0-20240125205218-1f4bbc51befe
	google.golang.org/genproto/googleapis/rpc v0.0.0-20240213162025-012b6fc9bca9
	google.golang.org/grpc v1.61.1
	google.golang.org/protobuf v1.32.0
)

require (
	github.com/benbjohnson/clock v1.3.5 // indirect
	github.com/mattn/go-runewidth v0.0.9 // indirect
	github.com/tidwall/match v1.1.1 // indirect
	github.com/tidwall/pretty v1.2.1 // indirect
	github.com/tidwall/sjson v1.2.5 // indirect
)

require (
	git.in.zhihu.com/bit/squirrel v1.6.0 // indirect
	git.in.zhihu.com/platform/sarama v1.43.3-0.0.4
	git.in.zhihu.com/platform/tetris v0.6.1-0.20240204081630-7686e94c42da // indirect
	git.in.zhihu.com/thrift-go/zrecall_service_thrift v0.0.0-20201104034835-182faa95a25b // indirect
	github.com/99designs/go-keychain v0.0.0-20191008050251-8e49817e8af4 // indirect
	github.com/Azure/azure-sdk-for-go/sdk/internal v1.10.0 // indirect
	github.com/DataDog/datadog-go/v5 v5.5.0 // indirect
	github.com/Masterminds/semver v1.5.0 // indirect
	github.com/Shopify/sarama v1.27.0 // indirect
	github.com/alecthomas/chroma v0.8.0 // indirect
	github.com/alibabacloud-go/alibabacloud-gateway-spi v0.0.5 // indirect
	github.com/alibabacloud-go/debug v1.0.1 // indirect
	github.com/alibabacloud-go/endpoint-util v1.1.0 // indirect
	github.com/alibabacloud-go/tea-xml v1.1.3 // indirect
	github.com/aliyun/credentials-go v1.3.10 // indirect
	github.com/allegro/bigcache/v3 v3.0.2 // indirect
	github.com/andybalholm/cascadia v1.3.2 // indirect
	github.com/armon/go-metrics v0.0.0-20190430140413-ec5e00d3c878 // indirect
	github.com/aws/aws-sdk-go v1.44.204 // indirect
	github.com/beltran/gosasl v0.0.0-20200715011608-d5475aebb293 // indirect
	github.com/beltran/gssapi v0.0.0-20200324152954-d86554db4bab // indirect
	github.com/bytedance/sonic v1.12.1 // indirect
	github.com/bytedance/sonic/loader v0.2.0 // indirect
	github.com/clbanning/mxj/v2 v2.5.5 // indirect
	github.com/cloudwego/base64x v0.1.4 // indirect
	github.com/cloudwego/iasm v0.2.0 // indirect
	github.com/danwakefield/fnmatch v0.0.0-20160403171240-cbb64ac3d964 // indirect
	github.com/dlclark/regexp2 v1.2.0 // indirect
	github.com/go-logfmt/logfmt v0.5.0 // indirect
	github.com/go-redis/redis/v8 v8.11.5 // indirect
	github.com/go-zookeeper/zk v1.0.1 // indirect
	github.com/hashicorp/consul/api v1.1.0 // indirect
	github.com/hashicorp/go-cleanhttp v0.5.1 // indirect
	github.com/hashicorp/go-immutable-radix v1.0.0 // indirect
	github.com/hashicorp/go-retryablehttp v0.7.0 // indirect
	github.com/hashicorp/go-rootcerts v1.0.0 // indirect
	github.com/hashicorp/serf v0.8.2 // indirect
	github.com/jcmturner/aescts/v2 v2.0.0 // indirect
	github.com/jcmturner/dnsutils/v2 v2.0.0 // indirect
	github.com/jcmturner/gokrb5/v8 v8.4.4 // indirect
	github.com/jcmturner/rpc/v2 v2.0.3 // indirect
	github.com/klauspost/cpuid/v2 v2.0.9 // indirect
	github.com/ks3sdklib/aws-sdk-go v1.2.9 // indirect
	github.com/mark3labs/mcp-go v0.42.0
	github.com/mitchellh/go-homedir v1.1.0 // indirect
	github.com/mohae/deepcopy v0.0.0-20170929034955-c48cc78d4826 // indirect
	github.com/opentracing-contrib/go-observer v0.0.0-20170622124052-a52f23424492 // indirect
	github.com/openzipkin-contrib/zipkin-go-opentracing v0.3.5 // indirect
	github.com/pierrec/lz4/v4 v4.1.21 // indirect
	github.com/richardlehane/mscfb v1.0.4 // indirect
	github.com/richardlehane/msoleps v1.0.3 // indirect
	github.com/tjfoc/gmsm v1.4.1 // indirect
	github.com/twitchyliquid64/golang-asm v0.15.1 // indirect
	github.com/xuri/efp v0.0.0-20230802181842-ad255f2331ca // indirect
	github.com/xuri/nfp v0.0.0-20230819163627-dc951e3ffe1a // indirect
	github.com/yosida95/uritemplate/v3 v3.0.2 // indirect
	go.opentelemetry.io/otel v1.27.0 // indirect
	go.uber.org/multierr v1.11.0 // indirect
	go.uber.org/zap v1.24.0 // indirect
	golang.org/x/arch v0.0.0-20210923205945-b76863e36670 // indirect
	google.golang.org/genproto v0.0.0-20240205150955-31a09d347014 // indirect
	gopkg.in/ini.v1 v1.67.0 // indirect
	gopkg.in/natefinch/lumberjack.v2 v2.0.0 // indirect
)

require (
	git.apache.org/thrift.git v0.0.0-20171203172758-327ebb6c2b6d
	git.in.zhihu.com/data/zlab-go v0.1.26 // indirect
	git.in.zhihu.com/data/zlab-proto v0.0.10-alpha // indirect
	git.in.zhihu.com/one-rpc-go/grpc-perception_prod v0.0.35 // indirect
	git.in.zhihu.com/one-rpc-go/grpc-tag-core v0.0.35
	git.in.zhihu.com/one-rpc-go/grpc-user_behavior v0.0.96 // indirect
	git.in.zhihu.com/one-rpc-go/grpc-user_core v0.0.57 // indirect
	git.in.zhihu.com/one-rpc-go/thrift-content_core v0.8.25-0.20250306150840-bed56d816d74
	git.in.zhihu.com/one-rpc-go/thrift-zrec-framework v0.0.0-20230925094930-f63e1e402d38 // indirect
	git.in.zhihu.com/pb-go/ad-proto v0.0.0-20211230093016-1184c6dff9bc // indirect
	git.in.zhihu.com/pb-go/feature-schema-proto v1.1.371
	git.in.zhihu.com/pb-go/search-proto v0.36.19-apigogov3
	git.in.zhihu.com/thrift-go/pico3_thrift v0.3.3 // indirect
	github.com/99designs/keyring v1.2.2 // indirect
	github.com/AthenZ/athenz v1.10.39 // indirect
	github.com/BurntSushi/toml v1.1.0 // indirect
	github.com/DataDog/zstd v1.5.0 // indirect
	github.com/GUAIK-ORG/go-snowflake v0.0.0-20200116064823-220c4260e85f // indirect
	github.com/Masterminds/semver/v3 v3.2.0 // indirect
	github.com/Microsoft/go-winio v0.6.2 // indirect
	github.com/RoaringBitmap/roaring v1.5.0 // indirect
	github.com/alicebob/gopher-json v0.0.0-20230218143504-906a9b012302 // indirect
	github.com/alicebob/miniredis v2.5.0+incompatible // indirect
	github.com/aliyun/aliyun-oss-go-sdk v2.1.4+incompatible // indirect
	github.com/andybalholm/brotli v1.0.5 // indirect
	github.com/apache/pulsar-client-go v0.8.0 // indirect
	github.com/apache/pulsar-client-go/oauth2 v0.0.0-20220120090717-25e59572242e // indirect
	github.com/ardielle/ardielle-go v1.5.2 // indirect
	github.com/beorn7/perks v1.0.1 // indirect
	github.com/bits-and-blooms/bitset v1.8.0 // indirect
	github.com/blang/semver v3.6.1+incompatible // indirect
	github.com/bmhatfield/go-runtime-metrics v0.0.0-20160512180836-3af15b63454c // indirect
	github.com/cep21/circuit/v3 v3.2.0 // indirect
	github.com/certifi/gocertifi v0.0.0-20210507211836-431795d63e8d // indirect
	github.com/cloudflare/circl v1.3.3 // indirect
	github.com/danieljoos/wincred v1.2.0 // indirect
	github.com/davecgh/go-spew v1.1.2-0.20180830191138-d8f796af33cc // indirect
	github.com/deckarep/golang-set v1.8.0
	github.com/dgryski/go-rendezvous v0.0.0-20200823014737-9f7001d12a5f // indirect
	github.com/dvsekhvalnov/jose2go v1.5.0 // indirect
	github.com/eapache/go-resiliency v1.7.0 // indirect
	github.com/eapache/go-xerial-snappy v0.0.0-20230731223053-c322873962e3 // indirect
	github.com/eapache/queue v1.1.0 // indirect
	github.com/envoyproxy/protoc-gen-validate v1.0.2 // indirect
	github.com/gaukas/godicttls v0.0.4 // indirect
	github.com/go-chi/cors v1.2.0 // indirect
	github.com/go-chi/render v1.0.1 // indirect
	github.com/go-sql-driver/mysql v1.7.1 // indirect
	github.com/go-task/slim-sprig v0.0.0-20230315185526-52ccab3ef572 // indirect
	github.com/goccy/go-json v0.10.2 // indirect
	github.com/godbus/dbus v0.0.0-20190726142602-4481cbc300e2 // indirect
	github.com/gogf/gf v1.16.9 // indirect
	github.com/gogo/protobuf v1.3.2
	github.com/golang-jwt/jwt v3.2.2+incompatible
	github.com/golang/glog v1.1.2 // indirect
	github.com/golang/mock v1.6.0 // indirect
	github.com/golang/snappy v0.0.4 // indirect
	github.com/gomodule/redigo v2.0.0+incompatible // indirect
	github.com/google/pprof v0.0.0-20240227163752-401108e1b7e7 // indirect
	github.com/gsterjov/go-libsecret v0.0.0-20161001094733-a6f4afe4910c // indirect
	github.com/hashicorp/errwrap v1.1.0 // indirect
	github.com/hashicorp/go-multierror v1.1.1 // indirect
	github.com/hashicorp/go-uuid v1.0.3 // indirect
	github.com/hashicorp/golang-lru v0.5.4 // indirect
	github.com/jcmturner/gofork v1.7.6 // indirect
	github.com/json-iterator/go v1.1.12
	github.com/klauspost/compress v1.17.9 // indirect
	github.com/lann/builder v0.0.0-20180802200727-47ae307949d0 // indirect
	github.com/lann/ps v0.0.0-20150810152359-62de8c46ede0 // indirect
	github.com/linkedin/goavro/v2 v2.9.8 // indirect
	github.com/mattn/go-sqlite3 v2.0.3+incompatible // indirect
	github.com/matttproud/golang_protobuf_extensions v1.0.1 // indirect
	github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd // indirect
	github.com/modern-go/reflect2 v1.0.2 // indirect
	github.com/mschoch/smat v0.2.0 // indirect
	github.com/mtibben/percent v0.2.1 // indirect
	github.com/onsi/ginkgo/v2 v2.12.0 // indirect
	github.com/opentracing/opentracing-go v1.2.0
	github.com/pierrec/lz4 v2.5.2+incompatible // indirect
	github.com/pmezard/go-difflib v1.0.1-0.20181226105442-5d4384ee4fb2 // indirect
	github.com/prometheus/client_golang v1.12.1 // indirect
	github.com/prometheus/client_model v0.4.0 // indirect
	github.com/prometheus/common v0.32.1 // indirect
	github.com/prometheus/procfs v0.7.3 // indirect
	github.com/quic-go/qpack v0.4.0 // indirect
	github.com/quic-go/qtls-go1-20 v0.3.3 // indirect
	github.com/quic-go/quic-go v0.38.1 // indirect
	github.com/rcrowley/go-metrics v0.0.0-20201227073835-cf1acfcdf475 // indirect
	github.com/refraction-networking/utls v1.5.3 // indirect
	github.com/sirupsen/logrus v1.9.3 // indirect
	github.com/spaolacci/murmur3 v1.1.0 // indirect
	github.com/uber/jaeger-client-go v2.30.0+incompatible // indirect
	github.com/uber/jaeger-lib v2.4.1+incompatible // indirect
	github.com/valyala/bytebufferpool v1.0.0 // indirect
	github.com/valyala/fasttemplate v1.2.2 // indirect
	github.com/vmihailenco/tagparser/v2 v2.0.0 // indirect
	github.com/yuin/gopher-lua v1.1.1 // indirect
	go.uber.org/atomic v1.11.0
	golang.org/x/crypto v0.32.0 // indirect
	golang.org/x/mod v0.18.0 // indirect
	golang.org/x/net v0.34.0
	golang.org/x/oauth2 v0.14.0 // indirect
	golang.org/x/sync v0.11.0 // indirect
	golang.org/x/sys v0.29.0 // indirect
	golang.org/x/term v0.28.0 // indirect
	golang.org/x/text v0.22.0 // indirect
	golang.org/x/time v0.3.0 // indirect
	golang.org/x/tools v0.22.0 // indirect
	google.golang.org/appengine v1.6.8 // indirect
	gopkg.in/alexcesaro/statsd.v2 v2.0.0 // indirect
	gopkg.in/jcmturner/aescts.v1 v1.0.1 // indirect
	gopkg.in/jcmturner/dnsutils.v1 v1.0.1 // indirect
	gopkg.in/jcmturner/gokrb5.v7 v7.5.0 // indirect
	gopkg.in/jcmturner/rpc.v1 v1.1.0 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)

replace (
	git.in.zhihu.com/data/ab-client/go => git.in.zhihu.com/data/ab-client/go v1.2.9
	git.in.zhihu.com/go/cafe => git.in.zhihu.com/wanghao11/cafe v1.0.6-0.20240621065341-f216f6b4e0c9
	git.in.zhihu.com/one-rpc-go/grpc-perception_prod => git.in.zhihu.com/pb-go/grpc-perception_prod v0.0.36-1-apigogov3
	git.in.zhihu.com/one-rpc-go/grpc-tag-core => git.in.zhihu.com/pb-go/grpc-tag-core v0.0.35-1-apigogov3
	git.in.zhihu.com/one-rpc-go/grpc-user_behavior => git.in.zhihu.com/pb-go/user_behavior v0.0.97-apigogov4
	git.in.zhihu.com/one-rpc-go/grpc-user_core => git.in.zhihu.com/pb-go/grpc-user_core v0.0.56-apigogov3
	git.in.zhihu.com/pb-go/feature-schema-proto => git.in.zhihu.com/pb-go/feature-schema-proto v1.1.267-apigogov3
	github.com/Azure/azure-sdk-for-go/sdk/ai/azopenai => git.in.zhihu.com/ai/azure-sdk/sdk/ai/azopenai v1.0.2-release
	github.com/Azure/azure-sdk-for-go/sdk/azcore => git.in.zhihu.com/ai/azure-sdk/sdk/azcore v1.9.3-0.20250709085739-8130c7c38f7e
	github.com/Azure/azure-sdk-for-go/sdk/internal => git.in.zhihu.com/ai/azure-sdk/sdk/internal v1.5.3-0.20250709085739-8130c7c38f7e
	github.com/gogo/protobuf => git.in.zhihu.com/zrec/gogofast_protobuf v0.0.2
	github.com/golang/protobuf => github.com/golang/protobuf v1.5.0
	github.com/mark3labs/mcp-go => git.in.zhihu.com/platform/mark3labs-mcp-go v0.27.1-0.20250512202050-20b3cb6cb3f6
)
