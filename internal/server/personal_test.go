package server

import (
	"github.com/gin-gonic/gin"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

func TestPersonalGraphQLGuard(t *testing.T) {
	t.Setenv("AXONHUB_PERSONAL_MODE", "true")
	for _, tt := range []struct {
		query string
		code  int
	}{
		{`mutation { x:createProject(input:{name:"x"}) { id } }`, 403},
		{`mutation { ...Team } fragment Team on Mutation { createUser(input:{email:"x"}) {id} }`, 403},
		{`mutation { createChannel(input:{name:"one"}) {id} }`, 200},
		{`query { projects {id} }`, 200},
	} {
		r := gin.New()
		r.POST("/", personalGraphQLGuard(), func(c *gin.Context) { c.Status(200) })
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"query":`+strconvQuote(tt.query)+`}`)))
		if w.Code != tt.code {
			t.Fatalf("%s: %d", tt.query, w.Code)
		}
	}
}
func strconvQuote(s string) string { return strconv.Quote(s) }
func TestPersonalOwnerRejectsUnauthenticatedCalls(t *testing.T) {
	r := gin.New()
	r.GET("/", personalOwner(), func(c *gin.Context) { c.Status(200) })
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/", nil))
	if w.Code != 403 {
		t.Fatal(w.Code)
	}
}
