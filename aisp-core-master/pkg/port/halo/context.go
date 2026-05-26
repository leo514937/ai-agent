package halo

import "context"

type serverInfoKey struct {
}

type ServerInfo struct {
	Region string
}

func ContextWithServerInfo(ctx context.Context, info ServerInfo) context.Context {
	return context.WithValue(ctx, serverInfoKey{}, info)
}

func ServerInfoFromContext(ctx context.Context) ServerInfo {
	info := ctx.Value(serverInfoKey{})
	if info == nil {
		return ServerInfo{}
	}
	out, ok := info.(ServerInfo)
	if !ok {
		return ServerInfo{}
	}
	return out
}
