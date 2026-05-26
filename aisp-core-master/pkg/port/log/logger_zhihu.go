package log

import (
	"context"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/logrus"
)

type ZhihuLogger struct {
	*logrus.Entry
}

func (l *ZhihuLogger) WithFields(ctx context.Context, fields map[string]interface{}) *ZhihuLogger {
	return wrap(log.StandardLogger().Logger.WithContext(ctx).WithFields(fields))
}

func (l *ZhihuLogger) WithField(ctx context.Context, key string, value interface{}) *ZhihuLogger {
	return wrap(l.Entry.WithContext(ctx).WithField(key, value))
}

func (l *ZhihuLogger) WithError(ctx context.Context, err error) *ZhihuLogger {
	return wrap(l.Entry.WithContext(ctx).WithError(err))
}

func (l *ZhihuLogger) Debug(ctx context.Context, args ...interface{}) {
	l.Entry.WithContext(ctx).Debug(args...)
}

func (l *ZhihuLogger) Debugf(ctx context.Context, format string, args ...interface{}) {
	l.Entry.WithContext(ctx).Debugf(format, args...)
}

func (l *ZhihuLogger) Info(ctx context.Context, args ...interface{}) {
	l.Entry.WithContext(ctx).Info(args...)
}

func (l *ZhihuLogger) Infof(ctx context.Context, format string, args ...interface{}) {
	l.Entry.WithContext(ctx).Infof(format, args...)
}

func (l *ZhihuLogger) Warn(ctx context.Context, args ...interface{}) {
	l.Entry.WithContext(ctx).Warn(args...)
}

func (l *ZhihuLogger) Warnf(ctx context.Context, format string, args ...interface{}) {
	l.Entry.WithContext(ctx).Warnf(format, args...)
}

func (l *ZhihuLogger) Error(ctx context.Context, args ...interface{}) {
	l.Entry.WithContext(ctx).Error(args...)
}

func (l *ZhihuLogger) Errorf(ctx context.Context, format string, args ...interface{}) {
	l.Entry.WithContext(ctx).Errorf(format, args...)
}

func wrap(entry *logrus.Entry) *ZhihuLogger {
	return &ZhihuLogger{Entry: entry}
}

func SetLevel(level log.Level) {
	log.SetLevel(level)
}

func GetLevel() log.Level {
	return log.GetLevel()
}

var logger = &ZhihuLogger{Entry: logrus.NewEntry(log.StandardLogger().Logger)}

func WithFields(ctx context.Context, fields map[string]interface{}) *ZhihuLogger {
	return wrap(log.StandardLogger().Logger.WithContext(ctx).WithFields(fields))
}

func WithField(ctx context.Context, key string, value interface{}) *ZhihuLogger {
	return wrap(log.StandardLogger().Logger.WithContext(ctx).WithField(key, value))
}

func WithError(ctx context.Context, err error) *ZhihuLogger {
	return wrap(log.StandardLogger().Logger.WithContext(ctx).WithError(err))
}

func Debug(ctx context.Context, args ...interface{}) {
	logger.WithContext(ctx).Debug(args...)
}

func Debugf(ctx context.Context, format string, args ...interface{}) {
	logger.WithContext(ctx).Debugf(format, args...)
}

func Info(ctx context.Context, args ...interface{}) {
	logger.WithContext(ctx).Info(args...)
}

func Infof(ctx context.Context, format string, args ...interface{}) {
	logger.WithContext(ctx).Infof(format, args...)
}

func Warn(ctx context.Context, args ...interface{}) {
	logger.WithContext(ctx).Warn(args...)
}

func Warnf(ctx context.Context, format string, args ...interface{}) {
	logger.WithContext(ctx).Warnf(format, args...)
}

func Error(ctx context.Context, args ...interface{}) {
	logger.WithContext(ctx).Error(args...)
}

func Errorf(ctx context.Context, format string, args ...interface{}) {
	logger.WithContext(ctx).Errorf(format, args...)
}
