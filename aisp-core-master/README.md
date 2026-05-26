# 统一 AI 服务平台 AISP (AI Service Platform)


## 相关文档


## 本地开发环境搭建


#### 第一步：配置 golang 开发环境

1. 安装 go sdk，配置 GOPATH
```
    brew install go@1.22
```

2. 本地新建一个目录，存放go代码，建议  `~/workspace/go`

3. 配置环境变量，如果本地使用bash，修改~/.bashrc，如果本地使用zsh，修改~/.zshrc

```
  export GOPATH={go_workspace_path}      #{go_workspace_path}是第二步自定义的go源码、项目存放路径，写自己设置的
  export GOROOT={go_path}   #{go_path}是go的安装目录，不知道的话，执行一下whereis go，例如输出为：/usr/local/go/bin/go，则go的安装目录是/usr/local/go
  export GO111MODULE=on    
  export GOPROXY=https://goproxy.in.zhihu.com,https://goproxy.cn,direct   ## 代理地址  按,分割
  export GOPRIVATE=git.in.zhihu.com
  export PATH=$PATH:$GOPATH/bin:$GOROOT/bin

```
3. source ~/.bashrc # 如果修改的~/.zshrc，就执行source ~/.zshrc

#### 下载代码


1. fork aisp-core 项目到个人空间下。
```
cd $GOPATH
git clone git@git.in.zhihu.com:{yourname}/aisp-core.git
git remote add upstream git@git.in.zhihu.com:zhihu/aisp-core.git
git fetch upstream
```
2. 使用 goland 打开项目
3. 项目验证

```
make fmt  // 无异常报错，同时无新 diff 产生，可以使用 git status 验证。
make all  // 无报错
```

## ZAE 服务启动命令

TODO


# 代码结构示例

                                                       A I S P
                                                         |
            ---------------------------------------------------------------------------------------------------
            对外接口                    |----pkg/portal
                                            |---grpc                    对外grpc接口
                                            |---consumer                消息consumer
            ---------------------------------------------------------------------------------------------------
            business(业务代码)          |----pkg/business
                                            |----AI 数字分身
                                            |----ai_tab
                                                 |----graph
                                                      |---- logic                        业务算子实现
                                                      |---- resource/logic_init.go       业务算子注册
                                                      |---- ai_tab_graph.go              业务算子编排
            ---------------------------------------------------------------------------------------------------
            framework(框架代码)    |----pkg
                                       |----port               针对公共库的二次封装，如 go/base 等等
                                       |----basic              基础组件，如 util、macro、dao、rpc封装
                                       |----core               核心实现（公共service等。逐步下线，相关逻辑向 graph 中算子化实现）
                                       |----graph              ZAG AI 引擎
                                              |----graph       graph的算子
                                       |----tools              工具包：主要用于测试、验证，无对在线有影响的逻辑！！！
            ---------------------------------------------------------------------------------------------------
            schema                |----proto


依赖关系为单向依赖：对外接口 -> business -> framework



    ├── Makefile
    ├── README.md
    ├── cmd                             // 启动入口
    │   ├── app-worker
    │   ├── arena-worker
    │   ├── asyncinvocation-worker
    │   ├── dashboard-web
    │   ├── dialoguetest
    │   ├── grpc
    │   ├── grpc-web
    │   └── grpcclient
    ├── gen-go                          // 自动生成的代码
    │   └── grpc                      // GRPC 相关
    ├── pkg
    │   ├── basic                 // 基础库的基本实现
    │   │   ├── dao
    │   │   ├── errors
    │   │   ├── macro
    │   │   ├── resource
    │   │   ├── rpc
    │   │   └── util
    │   ├── business              // 业务逻辑
    │   │   ├── aisservice
    │   │   ├── dashboard_zhihu
    │   │   └── shared
    │   ├── core
    │   │   ├── exception
    │   │   ├── model
    │   │   ├── service
    │   │   └── shared
    │   ├── port                  // 针对公司组件的封装
    │   │   ├── config
    │   │   ├── grpc
    │   │   ├── http
    │   │   ├── kafka
    │   │   ├── log
    │   │   ├── metrics
    │   │   ├── mysql
    │   │   └── redis
    │   └── portal
    │       ├── dashboard
    │       │   ├── handler_zhihu
    │       │   └── middleware
    │       └── grpc
    ├── playground                      //
    ├── playground.sh
    ├── proto
    └── requirements.txt


# 各层定义
- portal RPC入口层
    - grpc 对外grpc接口
    - zhihaitu 知海图 http接口
    - ...
- business 业务逻辑层，可以在该层下实现相关业务场景逻辑
    - business 1...3 目录可以根据自己业务场景自定义， 调用shared处理相关的业务场景逻辑
    - shared 实现功能组合和封装，实现主要业务逻辑，继续调用core-service处理通用逻辑
    - zhida_pro 直答专业版特殊业务逻辑
    - discover_tab 直答通搜版特殊业务逻辑
    - zhihaitu 知海图相关业务
    - ...
- graph ai引擎算子编排
    - entities 算子实体  
    - graph 公共算子库
    - resources 算子资源
      - ab ab实验
      - login_init
- core 核心领域层
    - model 核心领域层模型，供service调用
    - service 核心逻辑层，复用性较强的代码在这里实现，系统能否继续下沉并演变成平台的关键层
    - ...
- consumer 消费者层
    - bundle 注册消费者服务
    - module 业务model
    - process 执行器
- basic
    - resource 数据访问层封装，比如Redis、Mysql、Hbase、Pulsar等
    - dao 数据模型定义、数据库操作封装
    - util 工具辅助类，例如字符串处理、日期格式转换等
    - macro 项目会用到的常量
    - rpc 依赖的其他服务RPC接口的封装实现
 
- 参考
    - https://www.jianshu.com/p/e3dca8d5e9ee


## 公共技术文档

1. [知乎编码规范](http://wiki.in.zhihu.com/pages/viewpage.action?pageId=105775654)
2. [配置 CI](http://lavie.zhdocs.io/en/latest/user_guides/getting_started.html#joker-yml)
3. [ZAE 接入指南](http://wiki.in.zhihu.com/pages/viewpage.action?pageId=54390624)

## 如何发包？
1. 发 go 包使用云效发包
2. 发 java 包使用脚本发包，参见：
   - [jar-deploy/README.md](scripts/jar-deploy/README.md)


# 你的每个 MR，都是美好明天的保证❤！
