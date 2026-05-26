package main

import (
	proto "git.in.zhihu.com/zhihu/aisp-core/gen-go/grpc/zhihu/aisp_core_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	txn, ctx := log.StartTransaction("grpcclient")
	defer txn.End(ctx)

	conn, err := grpc.DialContext(ctx, "localhost:9999")
	if err != nil {
		panic(err)
	}

	client := proto.NewAispCoreServiceClient(conn)

	conversationRequest := &proto.CreateConversationRequest{
		TenantId: 90001,
		TaskId:   16,
	}
	conversationResponse, err := client.CreateConversation(ctx, conversationRequest)
	log.Infof(ctx, "request: %+v response: %+v err: %+v \n", conversationRequest, conversationResponse, err)

	content := "关键Rust开始进入了操作系统，而其他语言除了几十年前的C/C++，都没能进入操作系统（不算脚本类，可以写内核那种）。进入了操作系统，很多人认为意义不大，但进入了操作系统，意味着未来语言可以长期发展，看几十年C/C++因为进入了操作系统，外围配套程序需要使用，寿命会非常之长。一个语言只要寿命足够长，未来发展就有了保障。Go语言因为云计算才火的，而云计算不是操作系统，理论上未来可以使用一种新的软件可以代替云计算基础框架，没有形成更强的依赖性。而操作系统的依赖性非常强，更换操作系统的代价比想象的难。Rust另外一个强大的优点，是足够难，需要中级程度水平以上，才能开发出编译器不怎么报错的程序，这样保证了程度员质量，需要中级以上水平的程度员才能开发出Rust实用软件，保证了软件工程的质量，特别是大规模软件开发时，不用担心各种水平参差不齐程度导致最后的短板而漏水。反而c/c++就是这样，一堆高手程序员中混入一些低水平的，可以导致开发出来的软件Bug特别多，很多可能延伸到生产系统中去了，导致修复Bug的成本特别高。所以大公司有倾向使用Rust来保证软件的质量，这个保证是基于Rust编译器，而不是其他的软件工程手段，软件工程手段是需要外力，这个是内在的，在不同管理下还是有可能导致Bug产生到生产系统中，这样修复起来代价特别高。Rust不是吹，而是实际有编译器来保证开发出来的代码质量，写Rust很多是以前写C/C++的多，他们的水平在程度员中算是中高级，再学习Rust自然知道那处，特别是大型公司开的软件管理，就是需要Rust这种从编译器来保证软件质量，这个也是对过去软件工程软件质量管理的反思，就是从根本上解决开发出来的软件Bug少的问题，而且又不能大大牺牲性能，这个在Rust中达到了平衡。长期趋势来看，Rust未来会有很好的发展，因为大型软件公司需要这样的编程语言，需要这种强制性的编译器保证的语言，有客观的质量保证，而不是依靠于管理水平，管理制度，是客观的第三方软件质量保证，减少Bug可以降低开发大型软件的成本，有的Bug一旦出现在生产端，可能导致整个公司的利益的受损，而产生这个Bug可能一个低水平程度就够了，所以导致软件开发管理的成本特别高，而内置出厂质量严格检测，是这种更加先进的软件工程质量保证思想。从管理学，软件工程，软件质量，软件成本，Bug消除等多个维度看，Rust未来肯定会有很大的发展，越是大型项目，使用越多越是明白这一点。而这一点和过去的众多开发语言也是完全不一样的，性能+软件质量保证，达到了一种需要的平衡。这种把复杂摆在台面上，把Bug放在编译前消除，超严格的编译器，是过去各个主流语言所没有的，是一种新的基于软件工程前置质量检查的开发模式，相当于严进严出，编写代码难，编译代码难，但生成的质量高性能高，解决了过去软件工程的质量保证没有客观化问题。"
	dialogueRequest := &proto.CreateDialogueRequest{
		TenantId:       90001,
		TaskId:         26,
		ConversationId: conversationResponse.Id,
		UserMessage:    content,
	}
	dialogueResponse, err := client.CreateDialogue(ctx, dialogueRequest)
	log.Infof(ctx, "request: %+v response: %+v err: %+v \n", dialogueRequest, dialogueResponse, err)

	return
}
