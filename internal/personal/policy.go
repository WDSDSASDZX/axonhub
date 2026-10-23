// Package personal applies background recommendations after normal gateway eligibility checks.
package personal

import (
	"encoding/json"
	"errors"
	"os"
	"sync"
	"time"
)

type Rule struct {
	ChannelID    int      `json:"channel_id"`
	Models       []string `json:"models"`
	Eligible     bool     `json:"eligible"`
	RequireFresh bool     `json:"require_fresh"`
	Priority     int      `json:"priority"`
	Reason       string   `json:"reason"`
}
type Policy struct {
	Version     int       `json:"version"`
	GeneratedAt time.Time `json:"generated_at"`
	ExpiresAt   time.Time `json:"expires_at"`
	Rules       []Rule    `json:"rules"`
}
type Cache struct {
	mu      sync.Mutex
	path    string
	checked time.Time
	policy  *Policy
	err     error
}

func (c *Cache) Load(path string, now time.Time) (*Policy, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.path == path && now.Sub(c.checked) < time.Second {
		return c.policy, c.err
	}
	if c.path != path {
		c.policy = nil
	}
	c.path, c.checked = path, now
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		if c.policy != nil {
			c.err = errors.New("personal policy disappeared; restore the worker policy")
			return c.policy, c.err
		}
		c.err = nil
		return nil, nil
	}
	if err != nil {
		c.err = errors.New("cannot read personal policy")
		return c.policy, c.err
	}
	if len(data) > 1024*1024 {
		c.err = errors.New("personal policy too large")
		return c.policy, c.err
	}
	var p Policy
	if json.Unmarshal(data, &p) != nil || p.Version != 1 || p.GeneratedAt.IsZero() ||
		!p.ExpiresAt.After(p.GeneratedAt) || p.ExpiresAt.Sub(p.GeneratedAt) > 10*time.Minute ||
		p.GeneratedAt.After(now.Add(5*time.Second)) {
		c.err = errors.New("invalid personal policy")
		return c.policy, c.err
	}
	seen := map[int]bool{}
	for _, r := range p.Rules {
		if r.ChannelID <= 0 || seen[r.ChannelID] || r.Priority < 0 || len(r.Models) == 0 {
			c.err = errors.New("invalid personal policy rule")
			return c.policy, c.err
		}
		seen[r.ChannelID] = true
	}
	c.policy, c.err = &p, nil
	return c.policy, nil
}
func (p *Policy) Decision(channelID int, models []string, now time.Time) (bool, int, string) {
	for _, r := range p.Rules {
		if r.ChannelID != channelID {
			continue
		}
		if r.RequireFresh && !now.Before(p.ExpiresAt) {
			return false, r.Priority, "额度策略已过期"
		}
		if !r.Eligible {
			return false, r.Priority, r.Reason
		}
		for _, allowed := range r.Models {
			for _, model := range models {
				if allowed == "*" || allowed == model {
					return true, r.Priority, r.Reason
				}
			}
		}
		return false, r.Priority, "模型不在此额度策略的允许范围"
	}
	return true, 1 << 30, "原有渠道策略"
}
