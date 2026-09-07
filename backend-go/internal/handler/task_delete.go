package handler

import "github.com/gin-gonic/gin"

func (h *TaskHandler) Delete(
	c *gin.Context,
) {
	taskID, valid :=
		idParam(
			c,
		)

	if !valid {
		return
	}

	if err := h.s.Delete(
		c,
		uid(
			c,
		),
		taskID,
	); err != nil {
		domain(
			c,
			err,
		)

		return
	}

	ok(
		c,
		nil,
	)
}
