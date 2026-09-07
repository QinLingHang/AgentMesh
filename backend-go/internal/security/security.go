package security

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
	"time"
)

var ErrInvalidAccessToken = errors.New("invalid access token")

func HashPassword(p string) (string, error) {
	if len([]byte(p)) < 8 || len([]byte(p)) > 72 {
		return "", errors.New("password length must be 8-72 bytes")
	}
	b, e := bcrypt.GenerateFromPassword([]byte(p), bcrypt.DefaultCost)
	return string(b), e
}
func ComparePassword(h, p string) bool {
	return bcrypt.CompareHashAndPassword([]byte(h), []byte(p)) == nil
}
func GenerateRefreshToken() (string, string, error) {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		return "", "", e
	}
	raw := base64.RawURLEncoding.EncodeToString(b)
	return raw, HashRefreshToken(raw), nil
}
func HashRefreshToken(raw string) string {
	s := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(s[:])
}

type Claims struct {
	UserID int64  `json:"uid"`
	Email  string `json:"email"`
	jwt.RegisteredClaims
}
type JWTManager struct {
	secret []byte
	issuer string
	ttl    time.Duration
}

func NewJWTManager(secret, issuer string, ttl time.Duration) *JWTManager {
	return &JWTManager{[]byte(secret), issuer, ttl}
}
func (m *JWTManager) Generate(uid int64, email string) (string, error) {
	now := time.Now()
	c := Claims{UserID: uid, Email: email, RegisteredClaims: jwt.RegisteredClaims{Issuer: m.issuer, Subject: fmt.Sprintf("%d", uid), IssuedAt: jwt.NewNumericDate(now), ExpiresAt: jwt.NewNumericDate(now.Add(m.ttl))}}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, c).SignedString(m.secret)
}
func (m *JWTManager) Parse(raw string) (*Claims, error) {
	c := &Claims{}
	t, e := jwt.ParseWithClaims(raw, c, func(t *jwt.Token) (any, error) {
		if t.Method.Alg() != jwt.SigningMethodHS256.Alg() {
			return nil, ErrInvalidAccessToken
		}
		return m.secret, nil
	}, jwt.WithIssuer(m.issuer), jwt.WithExpirationRequired())
	if e != nil || !t.Valid || c.UserID <= 0 {
		return nil, ErrInvalidAccessToken
	}
	return c, nil
}
func (m *JWTManager) TTL() time.Duration { return m.ttl }
