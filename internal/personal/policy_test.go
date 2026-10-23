package personal

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPolicyEligibilityAndFreshness(t *testing.T) {
	now := time.Now()
	p := Policy{ExpiresAt: now.Add(time.Minute), Rules: []Rule{
		{ChannelID: 1, Models: []string{"json-model"}, Eligible: true, RequireFresh: true, Priority: 0},
		{ChannelID: 2, Models: []string{"*"}, Eligible: false, RequireFresh: true, Reason: "protected"},
	}}
	tests := []struct {
		id    int
		model string
		now   time.Time
		want  bool
	}{
		{1, "json-model", now, true}, {1, "other", now, false}, {2, "json-model", now, false},
		{3, "other", now, true}, {1, "json-model", now.Add(2 * time.Minute), false},
	}
	for _, tt := range tests {
		got, _, _ := p.Decision(tt.id, []string{tt.model}, tt.now)
		if got != tt.want {
			t.Fatalf("%+v got %v", tt, got)
		}
	}
}
func TestInvalidPolicyCannotDisableEnforcement(t *testing.T) {
	path := filepath.Join(t.TempDir(), "policy.json")
	now := time.Now().UTC().Truncate(time.Second)
	text := `{"version":1,"generated_at":"` + now.Format(time.RFC3339) + `","expires_at":"` + now.Add(time.Minute).Format(time.RFC3339) + `","rules":[{"channel_id":1,"models":["*"],"eligible":false,"priority":0}]}`
	if err := os.WriteFile(path, []byte(text), 0600); err != nil {
		t.Fatal(err)
	}
	var cache Cache
	if _, err := cache.Load(path, now); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("broken"), 0600); err != nil {
		t.Fatal(err)
	}
	p, err := cache.Load(path, now.Add(2*time.Second))
	if err == nil || p == nil {
		t.Fatal("invalid replacement must report error and retain last policy")
	}
}
