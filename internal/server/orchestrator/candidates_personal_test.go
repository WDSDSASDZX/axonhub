package orchestrator

import (
	"context"
	"encoding/json"
	"github.com/looplj/axonhub/internal/ent"
	"github.com/looplj/axonhub/internal/personal"
	"github.com/looplj/axonhub/internal/server/biz"
	"github.com/looplj/axonhub/llm"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPersonalRoutingFiltersProtectedChannelsAndRanksRemaining(t *testing.T) {
	path := filepath.Join(t.TempDir(), "policy.json")
	t.Setenv("AXONHUB_PERSONAL_POLICY_FILE", path)
	now := time.Now()
	p := personal.Policy{Version: 1, GeneratedAt: now, ExpiresAt: now.Add(time.Minute), Rules: []personal.Rule{
		{ChannelID: 1, Models: []string{"*"}, Eligible: true, RequireFresh: true, Priority: 2},
		{ChannelID: 2, Models: []string{"*"}, Eligible: true, RequireFresh: true, Priority: 0},
		{ChannelID: 3, Models: []string{"*"}, Eligible: false, RequireFresh: true, Priority: 1},
	}}
	data, _ := json.Marshal(p)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	var candidates []*ChannelModelsCandidate
	for _, id := range []int{1, 3, 2} {
		candidates = append(candidates, &ChannelModelsCandidate{Channel: &biz.Channel{Channel: &ent.Channel{ID: id}},
			Models: []biz.ChannelModelEntry{{RequestModel: "model", ActualModel: "model"}}})
	}
	got, err := applyPersonalPolicy(candidates, "model")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].Channel.ID != 2 || got[1].Channel.ID != 1 {
		t.Fatal("unexpected routing order")
	}
	// Filtering must not mutate shared candidate/model caches.
	if len(candidates) != 3 || len(candidates[1].Models) != 1 {
		t.Fatal("input mutated")
	}
}

func TestPersonalPriorityIsAppliedBeforeTopKTruncation(t *testing.T) {
	path := filepath.Join(t.TempDir(), "policy.json")
	t.Setenv("AXONHUB_PERSONAL_POLICY_FILE", path)
	now := time.Now()
	p := personal.Policy{Version: 1, GeneratedAt: now, ExpiresAt: now.Add(time.Minute)}
	var candidates []*ChannelModelsCandidate
	for id := 1; id <= 4; id++ {
		p.Rules = append(p.Rules, personal.Rule{ChannelID: id, Models: []string{"*"}, Eligible: true, RequireFresh: true, Priority: 4 - id})
		candidates = append(candidates, &ChannelModelsCandidate{Channel: &biz.Channel{Channel: &ent.Channel{ID: id}}, Models: []biz.ChannelModelEntry{{RequestModel: "model", ActualModel: "model"}}})
	}
	data, _ := json.Marshal(p)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	policy := &mockSystemService{retryPolicy: &biz.RetryPolicy{Enabled: false}}
	lb := NewLoadBalancer(policy, nil, &channelBasedStrategy{name: "score", scores: map[int]float64{1: 100, 2: 80, 3: 60, 4: 0}})
	selector := WithLoadBalancedSelector(&personalPolicySelector{wrapped: &mockSelector{candidates: candidates}}, lb, policy)
	got, err := selector.Select(context.Background(), &llm.Request{Model: "model"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Channel.ID != 4 {
		t.Fatal("expiry winner was dropped before policy selection")
	}
}
