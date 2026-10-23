package orchestrator

import (
	"context"
	"fmt"
	"os"
	"slices"
	"time"

	"github.com/looplj/axonhub/internal/personal"
	"github.com/looplj/axonhub/llm"
)

var personalPolicyCache personal.Cache

type personalPolicyContextKey struct{}

func personalPolicyActive(ctx context.Context) bool {
	active, _ := ctx.Value(personalPolicyContextKey{}).(bool)
	return active
}

func personalPolicyPath() string {
	if path := os.Getenv("AXONHUB_PERSONAL_POLICY_FILE"); path != "" {
		return path
	}
	return "data/personal/policy.json"
}

func personalPolicyManages(candidates []*ChannelModelsCandidate) bool {
	p, err := personalPolicyCache.Load(personalPolicyPath(), time.Now())
	if err != nil || p == nil {
		return false
	}
	for _, rule := range p.Rules {
		for _, candidate := range candidates {
			if rule.ChannelID == candidate.Channel.ID {
				return true
			}
		}
	}
	return false
}

type personalPolicySelector struct{ wrapped CandidateSelector }

func (s *personalPolicySelector) Select(ctx context.Context, req *llm.Request) ([]*ChannelModelsCandidate, error) {
	candidates, err := s.wrapped.Select(ctx, req)
	if err != nil {
		return nil, err
	}
	return applyPersonalPolicy(candidates, req.Model)
}

func applyPersonalPolicy(candidates []*ChannelModelsCandidate, requestedModel string) ([]*ChannelModelsCandidate, error) {
	path := personalPolicyPath()
	now := time.Now()
	policy, err := personalPolicyCache.Load(path, now)
	if err != nil {
		return nil, fmt.Errorf("personal routing policy unavailable: %w", err)
	}
	if policy == nil {
		return candidates, nil
	}
	type ranked struct {
		candidate *ChannelModelsCandidate
		priority  int
	}
	accepted := make([]ranked, 0, len(candidates))
	for _, candidate := range candidates {
		// Narrow individual model entries as well as channels: aliases may resolve to several models.
		copyCandidate := *candidate
		copyCandidate.Models = nil
		copyCandidate.modelAPIFormats = nil
		rank := 1 << 30
		for i, model := range candidate.Models {
			allowed, priority, _ := policy.Decision(candidate.Channel.ID, []string{requestedModel, model.RequestModel, model.ActualModel}, now)
			if !allowed {
				continue
			}
			copyCandidate.Models = append(copyCandidate.Models, model)
			if len(candidate.modelAPIFormats) > i {
				copyCandidate.modelAPIFormats = append(copyCandidate.modelAPIFormats, candidate.modelAPIFormats[i])
			}
			rank = min(rank, priority)
		}
		if len(copyCandidate.Models) > 0 {
			accepted = append(accepted, ranked{&copyCandidate, rank})
		}
	}
	slices.SortStableFunc(accepted, func(a, b ranked) int { return a.priority - b.priority })
	result := make([]*ChannelModelsCandidate, 0, len(accepted))
	for _, a := range accepted {
		result = append(result, a.candidate)
	}
	if len(candidates) > 0 && len(result) == 0 {
		return nil, NewQuotaExhaustedError(requestedModel)
	}
	return result, nil
}
