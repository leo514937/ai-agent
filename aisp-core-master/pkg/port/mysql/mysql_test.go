package mysql

func init() {
	NewConnection = func(name string) Connection {
		return nil
	}
}
