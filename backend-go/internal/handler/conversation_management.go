package handler

import "github.com/gin-gonic/gin"

func (h *ConversationHandler) Rename(
	c *gin.Context,
) {
	conversationID, valid :=
		idParam(
			c,
		)

	if !valid {
		return
	}

	var request struct {
		Title string `json:"title" binding:"required"`
	}

	if c.ShouldBindJSON(
		&request,
	) != nil {
		fail(
			c,
			400,
			40021,
			"会话名称不合法",
		)

		return
	}

	conversation, err :=
		h.s.Rename(
			c,
			uid(
				c,
			),
			conversationID,
			request.Title,
		)

	if err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		conversation,
	)
}
