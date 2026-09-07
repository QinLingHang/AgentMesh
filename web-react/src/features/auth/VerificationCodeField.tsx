import {
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  sendEmailCode,
} from "../../api";
import type {
  VerificationScene,
} from "../../api";

type Feedback =
  | {
      type:
        | "success"
        | "warning"
        | "error";
      message: string;
    }
  | null;

function normalizeEmail(
  value: string,
) {
  return value
    .trim()
    .toLowerCase();
}

function validEmail(
  value: string,
) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(
    value,
  );
}

function maskEmail(
  email: string,
) {
  const [
    local = "",
    domain = "",
  ] =
    email.split("@");

  if (!domain) {
    return email;
  }

  const prefix =
    local.length <= 2
      ? local.slice(0, 1)
      : local.slice(0, 2);

  return `${prefix}***@${domain}`;
}

function codeSendError(
  error: unknown,
  scene: VerificationScene,
): Feedback {
  if (
    error instanceof ApiError
  ) {
    if (
      scene === "register" &&
      error.code === 40901
    ) {
      return {
        type: "error",
        message:
          "该邮箱已经注册，无需重复注册。",
      };
    }

    if (
      error.code === 42911
    ) {
      return {
        type: "warning",
        message:
          "验证码请求过于频繁，请等待倒计时结束后再试。",
      };
    }

    if (
      error.code === 42912
    ) {
      return {
        type: "warning",
        message:
          "验证码发送次数已达到当前限制，请稍后再试。",
      };
    }

    if (
      error.code === 40013
    ) {
      return {
        type: "error",
        message:
          "邮箱格式不正确，请检查后重新输入。",
      };
    }

    if (
      error.status >= 500
    ) {
      return {
        type: "error",
        message:
          "验证码服务暂时不可用，请稍后重试。",
      };
    }
  }

  return {
    type: "error",
    message:
      error instanceof Error
        ? error.message
        : "验证码发送失败，请稍后重试。",
  };
}

export function VerificationCodeField({
  email,
  scene,
  code,
  onCodeChange,
  disabled = false,
  onGoToLogin,
}: {
  email: string;
  scene: VerificationScene;
  code: string;
  onCodeChange: (
    value: string,
  ) => void;
  disabled?: boolean;
  onGoToLogin?: () => void;
}) {
  const [
    sending,
    setSending,
  ] =
    useState(false);

  const [
    cooldown,
    setCooldown,
  ] =
    useState(0);

  const [
    feedback,
    setFeedback,
  ] =
    useState<Feedback>(
      null,
    );

  const [
    sentTo,
    setSentTo,
  ] =
    useState("");

  const codeRef =
    useRef<HTMLInputElement>(
      null,
    );

  const normalizedEmail =
    normalizeEmail(
      email,
    );

  useEffect(
    () => {
      if (cooldown <= 0) {
        return;
      }

      const timer =
        window.setInterval(
          () => {
            setCooldown(
              (value) =>
                value > 1
                  ? value - 1
                  : 0,
            );
          },
          1000,
        );

      return () =>
        window.clearInterval(
          timer,
        );
    },
    [cooldown],
  );

  // If the user changes the email after requesting a code,
  // the previous code belongs to the previous email.
  useEffect(
    () => {
      if (
        !sentTo ||
        normalizedEmail === sentTo
      ) {
        return;
      }

      setSentTo("");
      setCooldown(0);
      onCodeChange("");

      setFeedback({
        type: "warning",
        message:
          "邮箱已修改，请为当前邮箱重新获取验证码。",
      });
    },
    [
      normalizedEmail,
      onCodeChange,
      sentTo,
    ],
  );

  const send = async () => {
    if (!normalizedEmail) {
      setFeedback({
        type: "error",
        message:
          "请先输入邮箱地址。",
      });

      return;
    }

    if (
      !validEmail(
        normalizedEmail,
      )
    ) {
      setFeedback({
        type: "error",
        message:
          "邮箱格式不正确，请检查后重新输入。",
      });

      return;
    }

    try {
      setSending(true);
      setFeedback(null);

      const result =
        await sendEmailCode(
          normalizedEmail,
          scene,
        );

      setSentTo(
        normalizedEmail,
      );

      setCooldown(
        Math.max(
          0,
          Math.round(
            result.cooldownSeconds,
          ),
        ),
      );

      const minutes =
        Math.max(
          1,
          Math.ceil(
            result.expiresInSeconds /
              60,
          ),
        );

      if (
        scene === "register"
      ) {
        setFeedback({
          type: "success",
          message:
            `验证码已发送至 ${maskEmail(normalizedEmail)}，${minutes} 分钟内有效。`,
        });
      } else {
        // Do not reveal whether an account exists.
        setFeedback({
          type: "success",
          message:
            `如果该邮箱已绑定 AgentMesh，验证码将发送至 ${maskEmail(normalizedEmail)}。请检查收件箱和垃圾邮件。`,
        });
      }

      window.setTimeout(
        () =>
          codeRef.current?.focus(),
        0,
      );
    } catch (error) {
      setFeedback(
        codeSendError(
          error,
          scene,
        ),
      );
    } finally {
      setSending(false);
    }
  };

  const registered =
    scene === "register" &&
    feedback?.type ===
      "error" &&
    feedback.message.includes(
      "已经注册",
    );

  return (
    <div className="auth-code-block">
      <label className="field">
        <span>
          邮箱验证码
        </span>

        <div className="auth-code-row">
          <input
            ref={codeRef}
            value={code}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            disabled={disabled}
            placeholder="6 位验证码"
            data-testid={`auth-code-${scene}`}
            onChange={(event) => {
              const value =
                event.target.value
                  .replace(
                    /\D/g,
                    "",
                  )
                  .slice(
                    0,
                    6,
                  );

              onCodeChange(
                value,
              );
            }}
          />

          <button
            type="button"
            className="auth-code-button"
            data-testid={`auth-send-code-${scene}`}
            disabled={
              disabled ||
              sending ||
              cooldown > 0
            }
            onClick={() =>
              void send()
            }
          >
            {sending
              ? "发送中..."
              : cooldown > 0
                ? `${cooldown}s 后重发`
                : sentTo
                  ? "重新获取"
                  : "获取验证码"}
          </button>
        </div>
      </label>

      {feedback && (
        <div
          className={
            `auth-code-feedback ${feedback.type}`
          }
          role={
            feedback.type ===
            "error"
              ? "alert"
              : "status"
          }
        >
          <span>
            {feedback.message}
          </span>

          {registered &&
            onGoToLogin && (
              <button
                type="button"
                className="auth-inline-link"
                onClick={
                  onGoToLogin
                }
              >
                直接登录
              </button>
            )}
        </div>
      )}

      {sentTo && (
        <div className="auth-code-help">
          没收到？先检查垃圾邮件；倒计时结束后可以重新发送。
        </div>
      )}
    </div>
  );
}
