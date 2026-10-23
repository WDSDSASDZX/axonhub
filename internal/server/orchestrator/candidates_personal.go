package orchestrator

import (
	"fmt"
	"os"
	"slices"
	"time"

	"github.com/looplj/axonhub/internal/personal"
)

var personalPolicyCache personal.Cache

func applyPersonalPolicy(candidates []*ChannelModelsCandidate, requestedModel string) ([]*ChannelModelsCandidate, error) {
	path := os.Getenv("AXONHUB_PERSONAL_POLICY_FILE")
	if path == "" {
		path = "data/personal/policy.json"
	}
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
	return result, nil
}
