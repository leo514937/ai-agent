package util

import (
	"context"
	"sync"
	"time"

	"github.com/juju/ratelimit"
)

type DynamicRateLimiter interface {
	Wait(ctx context.Context)
}

type dynamicRateLimiterImpl struct {
	rateGetter func() float64
	limiter    *ratelimit.Bucket
	lastRate   float64
	rwlock     sync.RWMutex
}

func NewDynamicRateLimiter(rateGetter func() float64) DynamicRateLimiter {
	return &dynamicRateLimiterImpl{
		rateGetter: rateGetter,
		limiter:    ratelimit.NewBucketWithRate(rateGetter(), 1),
		lastRate:   rateGetter(),
	}
}

func (d *dynamicRateLimiterImpl) Wait(ctx context.Context) {
	for {
		rate := d.rateGetter()
		d.rwlock.RLock()
		lastRate := d.lastRate
		d.rwlock.RUnlock()

		if rate != lastRate {
			func() {
				d.rwlock.Lock()
				rate := d.rateGetter()
				if rate != d.lastRate {
					d.limiter = ratelimit.NewBucketWithRate(rate, 1)
					d.lastRate = rate
				}
				d.rwlock.Unlock()
			}()
		}
		if d.limiter.WaitMaxDuration(1, time.Millisecond*100) {
			return
		}
	}
}
