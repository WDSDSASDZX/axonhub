package server

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/parser"

	"github.com/looplj/axonhub/internal/contexts"
	"github.com/looplj/axonhub/internal/ent"
	"github.com/looplj/axonhub/internal/ent/channel"
	"github.com/looplj/axonhub/internal/objects"
	"github.com/looplj/axonhub/internal/server/biz"
)

func personalMode() bool { return os.Getenv("AXONHUB_PERSONAL_MODE") != "false" }

func personalOwner() gin.HandlerFunc {
	return func(c *gin.Context) {
		user, ok := contexts.GetUser(c.Request.Context())
		if !ok || !user.IsOwner {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "仅个人管理员可执行此操作"})
			return
		}
		c.Next()
	}
}

func personalTarget() (*url.URL, error) {
	address := os.Getenv("AXONHUB_PERSONAL_WORKER_URL")
	if address == "" {
		address = "http://127.0.0.1:8093"
	}
	u, err := url.Parse(address)
	if err != nil || u.Scheme != "http" || u.User != nil || u.Path != "" || u.RawQuery != "" ||
		(u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1" && u.Hostname() != "::1") {
		return nil, errors.New("invalid personal worker address")
	}
	return u, nil
}
func personalToken() (string, error) {
	path := os.Getenv("AXONHUB_PERSONAL_TOKEN_FILE")
	if path == "" {
		path = "data/personal/worker.token"
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", errors.New("personal worker is not configured")
	}
	token := strings.TrimSpace(string(data))
	if len(token) < 24 {
		return "", errors.New("invalid personal worker token")
	}
	return token, nil
}
func registerPersonalRoutes(group *gin.RouterGroup, channels *biz.ChannelService) {
	group.Any("/personal/*path", personalOwner(), func(c *gin.Context) {
		target, err := personalTarget()
		if err != nil {
			c.JSON(503, gin.H{"error": "个人版后台地址无效"})
			return
		}
		token, err := personalToken()
		if err != nil {
			c.JSON(503, gin.H{"error": "个人版后台未启动，请运行 personal worker"})
			return
		}
		path := c.Param("path")
		if path == "/connect" && c.Request.Method == http.MethodPost {
			connectJetHub(c, channels, target, token)
			return
		}
		allowed := map[string]string{"/status": "GET", "/rpc": "POST", "/budgets": "POST"}
		if allowed[path] != c.Request.Method {
			c.JSON(404, gin.H{"error": "未知个人版接口"})
			return
		}
		proxy := httputil.NewSingleHostReverseProxy(target)
		proxy.Transport = &http.Transport{ResponseHeaderTimeout: 50 * time.Second}
		proxy.Director = func(req *http.Request) {
			req.URL.Scheme, req.URL.Host, req.URL.Path, req.URL.RawQuery = target.Scheme, target.Host, path, ""
			req.Host = target.Host
			req.Header.Del("Cookie")
			req.Header.Del("X-Forwarded-For")
			req.Header.Set("Authorization", "Bearer "+token)
		}
		proxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, _ error) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(`{"error":"个人版后台暂时不可用"}`))
		}
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1024*1024)
		proxy.ServeHTTP(c.Writer, c.Request)
	})
}
func connectJetHub(c *gin.Context, svc *biz.ChannelService, target *url.URL, token string) {
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodGet, target.String()+"/connection", nil)
	if err != nil {
		c.JSON(503, gin.H{"error": "后台连接失败"})
		return
	}
	req.Header.Set("Authorization", "Bearer "+token)
	client := http.Client{Timeout: 50 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		c.JSON(503, gin.H{"error": "后台连接失败"})
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		c.JSON(502, gin.H{"error": "Jet Hub 尚未授权或模型网关不可用"})
		return
	}
	var data struct {
		Name    string   `json:"name"`
		BaseURL string   `json:"base_url"`
		APIKey  string   `json:"api_key"`
		Models  []string `json:"models"`
	}
	if json.NewDecoder(io.LimitReader(resp.Body, 4*1024*1024)).Decode(&data) != nil || len(data.Models) == 0 || data.APIKey == "" {
		c.JSON(502, gin.H{"error": "Jet Hub 未返回可用模型，请先登录账号"})
		return
	}
	base, err := url.Parse(data.BaseURL)
	if err != nil || base.Scheme != "http" || (base.Hostname() != "127.0.0.1" && base.Hostname() != "localhost" && base.Hostname() != "::1") {
		c.JSON(502, gin.H{"error": "Jet Hub 必须运行在本机"})
		return
	}
	created, err := svc.CreateChannel(c.Request.Context(), ent.CreateChannelInput{
		Type: channel.TypeOpenai, Name: "Jet Hub", BaseURL: &data.BaseURL,
		Credentials: objects.ChannelCredentials{APIKey: data.APIKey}, SupportedModels: data.Models,
		DefaultTestModel: data.Models[0], Tags: []string{"personal", "jet-hub"},
	})
	if err != nil {
		c.JSON(409, gin.H{"error": "连接未创建，请检查是否已有 Jet Hub 渠道"})
		return
	}
	c.JSON(201, gin.H{"id": created.ID, "name": created.Name, "models": len(data.Models)})
}

// Enforce the personal edition on GraphQL writes, including aliases and fragments.
func personalGraphQLGuard() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !personalMode() {
			c.Next()
			return
		}
		body, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, 4*1024*1024))
		if err != nil {
			c.AbortWithStatusJSON(413, gin.H{"error": "请求过大"})
			return
		}
		c.Request.Body = io.NopCloser(bytes.NewReader(body))
		var input struct {
			Query string `json:"query"`
		}
		if json.Unmarshal(body, &input) != nil {
			c.Next()
			return
		}
		doc, err := parser.ParseQuery(&ast.Source{Input: input.Query})
		if err != nil {
			c.Next()
			return
		}
		blocked := map[string]bool{
			"createUser": true, "updateUserStatus": true, "deleteUser": true,
			"createRole": true, "updateRole": true, "deleteRole": true,
			"createProject": true, "updateProject": true, "updateProjectStatus": true,
			"deleteProject": true, "addUserToProject": true, "removeUserFromProject": true, "updateProjectUser": true,
		}
		var denied func(ast.SelectionSet, map[string]bool) bool
		denied = func(selection ast.SelectionSet, seen map[string]bool) bool {
			for _, node := range selection {
				switch n := node.(type) {
				case *ast.Field:
					if blocked[n.Name] {
						return true
					}
				case *ast.InlineFragment:
					if denied(n.SelectionSet, seen) {
						return true
					}
				case *ast.FragmentSpread:
					if !seen[n.Name] {
						seen[n.Name] = true
						if fragment := doc.Fragments.ForName(n.Name); fragment != nil && denied(fragment.SelectionSet, seen) {
							return true
						}
					}
				}
			}
			return false
		}
		for _, op := range doc.Operations {
			if op.Operation == ast.Mutation && denied(op.SelectionSet, map[string]bool{}) {
				c.AbortWithStatusJSON(403, gin.H{"error": "个人版已关闭团队、角色和项目管理操作"})
				return
			}
		}
		c.Next()
	}
}
