package middleware

import (
	"context"
	"example.com/agentmesh-control-plane/internal/security"
	"fmt"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"net/http"
	"strings"
	"time"
)

const UserIDKey = "auth.user_id"

func Auth(jwt *security.JWTManager) gin.HandlerFunc {
	return func(c *gin.Context) {
		parts := strings.Fields(strings.TrimSpace(c.GetHeader("Authorization")))
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			unauthorized(c)
			return
		}
		claims, e := jwt.Parse(parts[1])
		if e != nil {
			unauthorized(c)
			return
		}
		c.Set(UserIDKey, claims.UserID)
		c.Next()
	}
}
func UserID(c *gin.Context) (int64, bool) {
	v, ok := c.Get(UserIDKey)
	if !ok {
		return 0, false
	}
	id, ok := v.(int64)
	return id, ok
}
func CORS(origins []string) gin.HandlerFunc {
	allowed := map[string]struct{}{}
	for _, o := range origins {
		allowed[o] = struct{}{}
	}
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if _, ok := allowed[origin]; ok {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Credentials", "true")
			c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type")
			c.Header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
			c.Header("Vary", "Origin")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
func FixedWindowRateLimit(rdb *redis.Client, limit int, window time.Duration) gin.HandlerFunc {
	return func(c *gin.Context) {
		uid, ok := UserID(c)
		if !ok {
			unauthorized(c)
			return
		}
		bucket := time.Now().Unix() / int64(window.Seconds())
		key := fmt.Sprintf("agentmesh:rate:task:%d:%d", uid, bucket)
		ctx, cancel := context.WithTimeout(c.Request.Context(), 800*time.Millisecond)
		defer cancel()
		n, e := rdb.Incr(ctx, key).Result()
		if e == nil && n == 1 {
			_ = rdb.Expire(ctx, key, window+5*time.Second).Err()
		}
		if e != nil {
			c.Next()
			return
		}
		if n > int64(limit) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"code": 42901, "message": "浠诲姟鎻愪氦杩囦簬棰戠箒锛岃绋嶅悗鍐嶈瘯", "data": nil})
			return
		}
		c.Next()
	}
}
func unauthorized(c *gin.Context) {
	c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"code": 40100, "message": "鏈櫥褰曟垨璁块棶浠ょ墝鏃犳晥", "data": nil})
}
