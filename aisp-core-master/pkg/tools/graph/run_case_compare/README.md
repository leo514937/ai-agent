# 带有编排的快速 case 对比

## 相关文档
1. 需求沟通：https://one.in.zhihu.com/rfcs/55335
2. 技术方案：https://one.in.zhihu.com/rfcs/55514

## 适用场景
1. 服务端到端进行 case 对比，对外服务结果一致，相比于 playground，带上了安全策略与架最新变更 
2. 对算子进行控制变量，例如对比两个模型的结果，脚本会自动推导需要保持一致的算子输出，控制召回内容等一致

## 使用方式
### 第一步：创建一个调试容器
服务选择 aisp-core-grpc-service，当前目录下操作

### 第二步：准备 case 文件
1. case 文件格式为 excel，只有一个 sheet，第一列为 memberId，第二列为输入 query
2. 放置于 pkg/tools/graph/run_case_compare/cases/ 目录下，命名为 $casesFileName，以 .xlsx 结尾，参考 pkg/tools/graph/run_case_compare/cases/demo.xlsx

### 第三步：准备 config 文件
1. 格式

   | 字段名  |             字段类型              |                           类型说明                           |       描述       |                                       说明                                        | 
   |:----:|:-----------------------------:|:--------------------------------------------------------:|:--------------:|:-------------------------------------------------------------------------------:| 
   | exp_name |            string             |                          string                          |     实验组名称      |                                    用于在结果中展示                                     |
   | config_map | map[string]map[string]string  | 1. 第一个key为算子名称<br/>2. 第二个key为配置key<br/>3. value 为配置value | 发生变更的算子 config | 注意：<br/>1. 只填写变更的算子配置，不变的不用填写。<br/>2.可以填写多个 <br/>3.框架会根据变更算子，自动推导受影响算子，其余算子控制变量 | 
   | ab_param_value | map[string]map[string]string  |    1. 第一个为实验场景名称<br/>2. 第二个key为实验参数<br/>3. value 为实验值    |    指定的ab实验参数值     |                             【不必填】当需要控制样本必须走某个实验组时填充                             |

2. 放置于 pkg/tools/graph/run_case_compare/conf/ 目录下，命名为 $confFileName，以 .json 结尾，参考 pkg/tools/graph/run_case_compare/conf/demo.json

### 第四步：启动脚本
在项目根目录（一般为/data/apps/aisp-core）下执行

1. 使用 demo 快速体验
```
   nohup go run pkg/tools/graph/run_case_compare/main.go 2>&1 >log.log &
```
2. 使用替换参数
```
   nohup go run pkg/tools/graph/run_case_compare/main.go -b=14 -m=0 -case=demo -conf=demo 2>&1 >log.log &
```
1. -b 代表场景，枚举类型如 proto/grpc/aisp_core_service/main.proto/ChatType
2. -case 代表 case 文件名，用上面的 $casesFileName，不带 .xlsx
3. -conf 代表 config 文件名，用上面的 $confFileName，不带 .json

脚本执行完之后，会在当前目录生成三个文件
1. case_output_yyyyMMddHHmmss.xlsx 为产出的 case 执行结果，只能在脚本执行完成时查看
2. process_log_yyyyMMddHHmmss.txt 为脚本执行日志，流式产出，可以 tail -f 持续查看