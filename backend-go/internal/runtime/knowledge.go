package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strconv"
	"time"

	"example.com/agentmesh-control-plane/internal/model"
)

type KnowledgeIndexResponse struct {
	ChunkCount int `json:"chunkCount"`
}

func (c *Client) IndexKnowledge(
	ctx context.Context,
	file model.KnowledgeFile,
	source io.Reader,
) (*KnowledgeIndexResponse, error) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	fields := map[string]string{
		"userId":          strconv.FormatInt(file.UserID, 10),
		"knowledgeBaseId": strconv.FormatInt(file.KnowledgeBaseID, 10),
		"knowledgeFileId": strconv.FormatInt(file.ID, 10),
		"originalName":    file.OriginalName,
		"extension":       file.Extension,
		"checksumSha256":  file.ChecksumSHA256,
	}
	if file.ProjectID != nil {
		fields["projectId"] = strconv.FormatInt(*file.ProjectID, 10)
	}

	for key, value := range fields {
		if err := writer.WriteField(key, value); err != nil {
			return nil, err
		}
	}

	part, err := writer.CreateFormFile("file", file.OriginalName)
	if err != nil {
		return nil, err
	}
	if _, err = io.Copy(part, source); err != nil {
		return nil, err
	}
	if err = writer.Close(); err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/internal/v1/knowledge/index",
		&body,
	)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Internal-Token", c.token)

	timeout := c.http.Timeout
	if timeout < 10*time.Minute {
		timeout = 10 * time.Minute
	}
	client := &http.Client{Timeout: timeout}

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode/100 != 2 {
		payload, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("knowledge runtime index returned %s: %s", resp.Status, string(payload))
	}

	var out KnowledgeIndexResponse
	if err = json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if out.ChunkCount <= 0 {
		return nil, fmt.Errorf("knowledge runtime returned empty index")
	}

	return &out, nil
}

func (c *Client) DeleteKnowledge(
	ctx context.Context,
	file model.KnowledgeFile,
) error {
	payload, err := json.Marshal(map[string]any{
		"userId":          file.UserID,
		"knowledgeBaseId": file.KnowledgeBaseID,
		"knowledgeFileId": file.ID,
	})
	if err != nil {
		return err
	}

	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodDelete,
		c.baseURL+"/internal/v1/knowledge/index",
		bytes.NewReader(payload),
	)
	if err != nil {
		return err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Token", c.token)

	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode/100 != 2 {
		payload, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("knowledge runtime delete returned %s: %s", resp.Status, string(payload))
	}

	return nil
}
