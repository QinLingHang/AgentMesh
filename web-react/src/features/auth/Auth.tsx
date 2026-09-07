import {
  useMemo,
  useState,
} from "react";
import {
  ApiError,
  login,
  loginWithCode,
  registerVerified,
  resetPassword,
} from "../../api";
import type {
  User,
} from "../../types";
import {
  VerificationCodeField,
} from "./VerificationCodeField";

type AuthView =
  | "login"
  | "register"
  | "forgot";

type LoginMethod =
  | "password"
  | "code";

function validPassword(
  value: string,
) {
  const bytes =
    new TextEncoder().encode(
      value,
    ).length;

  return (
    bytes >= 8 &&
    bytes <= 72
  );
}

function friendlySubmitError(
  error: unknown,
  action:
    | "password_login"
    | "code_login"
    | "register"
    | "reset",
) {
  if (
    error instanceof ApiError
  ) {
    if (
      action ===
        "password_login" &&
      error.code === 40101
    ) {
      return "邮箱或密码错误，请检查后重试。";
    }

    if (
      action === "code_login" &&
      error.code === 40102
    ) {
      return "邮箱或验证码无效，请确认验证码是否正确或已过期。";
    }

    if (
      action === "register" &&
      error.code === 40901
    ) {
      return "该邮箱已经注册，请直接返回登录。";
    }

    if (
      action === "register" &&
      error.code === 40015
    ) {
      return "验证码无效、已过期或尝试次数过多，请重新获取验证码。";
    }

    if (
      action === "reset" &&
      error.code === 40018
    ) {
      return "验证码无效、已过期或尝试次数过多，请重新获取验证码。";
    }

    if (
      error.status >= 500
    ) {
      return "账户服务暂时不可用，请稍后重试。";
    }

    if (
      error.message &&
      !/[鐧閭娉鍙傚弬]/.test(
        error.message,
      )
    ) {
      return error.message;
    }
  }

  return error instanceof Error
    ? error.message
    : "操作失败，请稍后重试。";
}

function PasswordField({
  label,
  value,
  autoComplete,
  placeholder,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  autoComplete:
    | "current-password"
    | "new-password";
  placeholder: string;
  disabled: boolean;
  onChange: (
    value: string,
  ) => void;
}) {
  const [
    visible,
    setVisible,
  ] =
    useState(false);

  return (
    <label className="field">
      <span>
        {label}
      </span>

      <div className="auth-password-row">
        <input
          value={value}
          type={
            visible
              ? "text"
              : "password"
          }
          autoComplete={
            autoComplete
          }
          disabled={disabled}
          placeholder={
            placeholder
          }
          onChange={(event) =>
            onChange(
              event.target.value,
            )
          }
        />

        <button
          type="button"
          className="auth-password-toggle"
          aria-label={
            visible
              ? "隐藏密码"
              : "显示密码"
          }
          onClick={() =>
            setVisible(
              (value) =>
                !value,
            )
          }
        >
          {visible
            ? "隐藏"
            : "显示"}
        </button>
      </div>
    </label>
  );
}

export function Auth({
  onDone,
}: {
  onDone: (
    user: User,
  ) => void;
}) {
  const [view, setView] =
    useState<AuthView>(
      "login",
    );

  const [
    loginMethod,
    setLoginMethod,
  ] =
    useState<LoginMethod>(
      "password",
    );

  const [email, setEmail] =
    useState("");

  const [
    password,
    setPassword,
  ] =
    useState("");

  const [
    confirmPassword,
    setConfirmPassword,
  ] =
    useState("");

  const [
    displayName,
    setDisplayName,
  ] =
    useState("");

  const [code, setCode] =
    useState("");

  const [
    newPassword,
    setNewPassword,
  ] =
    useState("");

  const [
    confirmNewPassword,
    setConfirmNewPassword,
  ] =
    useState("");

  const [error, setError] =
    useState("");

  const [
    notice,
    setNotice,
  ] =
    useState("");

  const [busy, setBusy] =
    useState(false);

  const title = useMemo(
    () => {
      if (view === "register") {
        return {
          heading:
            "创建 AgentMesh 账户",
          description:
            "验证邮箱并设置密码。注册完成后可使用密码或验证码登录。",
        };
      }

      if (view === "forgot") {
        return {
          heading:
            "找回密码",
          description:
            "邮箱验证通过后才能修改密码；修改成功会使旧登录会话失效。",
        };
      }

      return {
        heading:
          "欢迎回来",
        description:
          "支持密码与邮箱验证码两种登录方式；活跃会话自动续期。",
      };
    },
    [view],
  );

  const resetFeedback =
    () => {
      setError("");
      setNotice("");
    };

  const switchView = (
    next: AuthView,
  ) => {
    setView(next);
    setCode("");
    setConfirmPassword("");
    setNewPassword("");
    setConfirmNewPassword("");
    resetFeedback();
  };

  const goToLogin = () => {
    switchView(
      "login",
    );

    setLoginMethod(
      "password",
    );
  };

  const submitPasswordLogin =
    async () => {
      if (
        !email.trim() ||
        !password
      ) {
        setError(
          "请输入邮箱和密码。",
        );

        return;
      }

      try {
        setBusy(true);
        resetFeedback();

        const user =
          await login(
            email.trim(),
            password,
          );

        onDone(user);
      } catch (error) {
        setError(
          friendlySubmitError(
            error,
            "password_login",
          ),
        );
      } finally {
        setBusy(false);
      }
    };

  const submitCodeLogin =
    async () => {
      if (
        !email.trim() ||
        code.length !== 6
      ) {
        setError(
          "请输入邮箱和 6 位验证码。",
        );

        return;
      }

      try {
        setBusy(true);
        resetFeedback();

        const user =
          await loginWithCode(
            email.trim(),
            code,
          );

        onDone(user);
      } catch (error) {
        setError(
          friendlySubmitError(
            error,
            "code_login",
          ),
        );
      } finally {
        setBusy(false);
      }
    };

  const submitRegister =
    async () => {
      if (
        !email.trim() ||
        code.length !== 6 ||
        !displayName.trim()
      ) {
        setError(
          "请完整填写邮箱、验证码和昵称。",
        );

        return;
      }

      if (
        !validPassword(
          password,
        )
      ) {
        setError(
          "密码长度需为 8–72 字节。",
        );

        return;
      }

      if (
        password !==
        confirmPassword
      ) {
        setError(
          "两次输入的密码不一致。",
        );

        return;
      }

      try {
        setBusy(true);
        resetFeedback();

        const user =
          await registerVerified(
            email.trim(),
            code,
            password,
            displayName.trim(),
          );

        onDone(user);
      } catch (error) {
        setError(
          friendlySubmitError(
            error,
            "register",
          ),
        );
      } finally {
        setBusy(false);
      }
    };

  const submitReset =
    async () => {
      if (
        !email.trim() ||
        code.length !== 6
      ) {
        setError(
          "请输入邮箱和 6 位验证码。",
        );

        return;
      }

      if (
        !validPassword(
          newPassword,
        )
      ) {
        setError(
          "新密码长度需为 8–72 字节。",
        );

        return;
      }

      if (
        newPassword !==
        confirmNewPassword
      ) {
        setError(
          "两次输入的新密码不一致。",
        );

        return;
      }

      try {
        setBusy(true);
        resetFeedback();

        await resetPassword(
          email.trim(),
          code,
          newPassword,
        );

        setPassword("");
        setCode("");
        setNewPassword("");
        setConfirmNewPassword("");

        setView(
          "login",
        );

        setLoginMethod(
          "password",
        );

        setNotice(
          "密码已重置。旧登录会话已失效，请使用新密码重新登录。",
        );
      } catch (error) {
        setError(
          friendlySubmitError(
            error,
            "reset",
          ),
        );
      } finally {
        setBusy(false);
      }
    };

  const submitCurrent =
    async () => {
      if (
        view === "register"
      ) {
        await submitRegister();

        return;
      }

      if (
        view === "forgot"
      ) {
        await submitReset();

        return;
      }

      if (
        loginMethod ===
        "code"
      ) {
        await submitCodeLogin();

        return;
      }

      await submitPasswordLogin();
    };

  const passwordMismatch =
    view === "register" &&
    confirmPassword.length > 0 &&
    password !==
      confirmPassword;

  const resetMismatch =
    view === "forgot" &&
    confirmNewPassword.length >
      0 &&
    newPassword !==
      confirmNewPassword;

  return (
    <div className="auth-page" data-testid="auth-page">
      <section className="auth-visual">
        <div className="auth-logo">
          AM
        </div>

        <div className="auth-copy">
          <div className="eyebrow auth-eyebrow">
            AGENT INFRASTRUCTURE
          </div>

          <h1>
            AgentMesh
          </h1>

          <p>
            面向多智能体协作、知识检索与工具执行的
            智能体运行控制平台。
          </p>

          <div className="auth-security-card">
            <strong>
              账户安全
            </strong>

            <span>
              邮箱验证 · 密码 / 验证码双登录 ·
              Refresh Token Rotation · 3 天滑动会话
            </span>
          </div>
        </div>

        <div className="auth-points">
          <span>
            智能路由
          </span>

          <span>
            智能检索增强
          </span>

          <span>
            运行状态监控
          </span>
        </div>
      </section>

      <section className="auth-main">
        <form
          className="auth-form"
          data-testid={`auth-${view}-form`}
          onSubmit={(event) => {
            event.preventDefault();

            void submitCurrent();
          }}
        >
          <div className="auth-title">
            <h2>
              {title.heading}
            </h2>

            <p>
              {title.description}
            </p>
          </div>

          {notice && (
            <div
              className="auth-notice"
              role="status"
            >
              {notice}
            </div>
          )}

          {view === "login" && (
            <div className="auth-method-tabs">
              <button
                type="button"
                className={
                  loginMethod ===
                  "password"
                    ? "active"
                    : ""
                }
                data-testid="auth-password-login-tab"
                onClick={() => {
                  setLoginMethod(
                    "password",
                  );

                  setCode("");
                  resetFeedback();
                }}
              >
                密码登录
              </button>

              <button
                type="button"
                className={
                  loginMethod ===
                  "code"
                    ? "active"
                    : ""
                }
                data-testid="auth-code-login-tab"
                onClick={() => {
                  setLoginMethod(
                    "code",
                  );

                  setPassword("");
                  resetFeedback();
                }}
              >
                验证码登录
              </button>
            </div>
          )}

          <label className="field">
            <span>
              邮箱
            </span>

            <input
              value={email}
              type="email"
              autoComplete="email"
              disabled={busy}
              placeholder="name@example.com"
              data-testid="auth-email"
              onChange={(event) => {
                setEmail(
                  event.target.value,
                );

                if (error) {
                  setError("");
                }
              }}
            />
          </label>

          {view === "login" &&
            loginMethod ===
              "password" && (
              <>
                <PasswordField
                  label="密码"
                  value={password}
                  autoComplete="current-password"
                  disabled={busy}
                  placeholder="输入密码"
                  onChange={
                    setPassword
                  }
                />

                <div className="auth-inline-action">
                  <button
                    type="button"
                    className="auth-link-button"
                    onClick={() =>
                      switchView(
                        "forgot",
                      )
                    }
                  >
                    忘记密码？
                  </button>
                </div>
              </>
            )}

          {view === "login" &&
            loginMethod ===
              "code" && (
              <VerificationCodeField
                key="login-code"
                email={email}
                scene="login"
                code={code}
                disabled={busy}
                onCodeChange={
                  setCode
                }
              />
            )}

          {view === "register" && (
            <>
              <VerificationCodeField
                key="register-code"
                email={email}
                scene="register"
                code={code}
                disabled={busy}
                onCodeChange={
                  setCode
                }
                onGoToLogin={
                  goToLogin
                }
              />

              <label className="field">
                <span>
                  昵称
                </span>

                <input
                  value={
                    displayName
                  }
                  autoComplete="name"
                  disabled={busy}
                  placeholder="你的显示名称"
                  onChange={(event) =>
                    setDisplayName(
                      event.target.value,
                    )
                  }
                />
              </label>

              <PasswordField
                label="设置密码"
                value={password}
                autoComplete="new-password"
                disabled={busy}
                placeholder="至少 8 个字符"
                onChange={
                  setPassword
                }
              />

              <div className="auth-field-hint">
                密码长度需为 8–72 字节。
              </div>

              <PasswordField
                label="确认密码"
                value={
                  confirmPassword
                }
                autoComplete="new-password"
                disabled={busy}
                placeholder="再次输入密码"
                onChange={
                  setConfirmPassword
                }
              />

              {passwordMismatch && (
                <div
                  className="auth-field-error"
                  role="alert"
                >
                  两次输入的密码不一致。
                </div>
              )}
            </>
          )}

          {view === "forgot" && (
            <>
              <VerificationCodeField
                key="reset-code"
                email={email}
                scene="reset_password"
                code={code}
                disabled={busy}
                onCodeChange={
                  setCode
                }
              />

              <PasswordField
                label="新密码"
                value={
                  newPassword
                }
                autoComplete="new-password"
                disabled={busy}
                placeholder="设置新的登录密码"
                onChange={
                  setNewPassword
                }
              />

              <div className="auth-field-hint">
                验证邮箱后才能修改密码；修改成功会退出其他旧会话。
              </div>

              <PasswordField
                label="确认新密码"
                value={
                  confirmNewPassword
                }
                autoComplete="new-password"
                disabled={busy}
                placeholder="再次输入新密码"
                onChange={
                  setConfirmNewPassword
                }
              />

              {resetMismatch && (
                <div
                  className="auth-field-error"
                  role="alert"
                >
                  两次输入的新密码不一致。
                </div>
              )}
            </>
          )}

          {error && (
            <div
              className="error-box auth-submit-error"
              role="alert"
            >
              {error}

              {view ===
                "register" &&
                error.includes(
                  "已经注册",
                ) && (
                  <button
                    type="button"
                    className="auth-inline-link"
                    onClick={
                      goToLogin
                    }
                  >
                    直接登录
                  </button>
                )}
            </div>
          )}

          <button
            type="submit"
            className="primary-button full-button auth-submit"
            data-testid="auth-submit"
            disabled={
              busy ||
              passwordMismatch ||
              resetMismatch
            }
          >
            {busy
              ? "处理中..."
              : view ===
                    "register"
                ? "验证邮箱并创建账户"
                : view ===
                      "forgot"
                  ? "验证身份并重置密码"
                  : loginMethod ===
                        "code"
                    ? "使用验证码登录"
                    : "登录 AgentMesh"}
          </button>

          <div className="auth-switch">
            {view === "login" && (
              <>
                <span>
                  还没有账户？
                </span>

                <button
                  type="button"
                  className="auth-link-button"
                  data-testid="auth-open-register"
                  onClick={() =>
                    switchView(
                      "register",
                    )
                  }
                >
                  创建账户
                </button>
              </>
            )}

            {view === "register" && (
              <>
                <span>
                  已有账户？
                </span>

                <button
                  type="button"
                  className="auth-link-button"
                  data-testid="auth-back-login"
                  onClick={
                    goToLogin
                  }
                >
                  返回登录
                </button>
              </>
            )}

            {view === "forgot" && (
              <>
                <span>
                  想起密码了？
                </span>

                <button
                  type="button"
                  className="auth-link-button"
                  onClick={
                    goToLogin
                  }
                >
                  返回登录
                </button>
              </>
            )}
          </div>

          <div className="auth-session-note">
            <span className="auth-session-dot" />

            活跃会话保持 3 天；正常使用时静默续期。
          </div>
        </form>
      </section>
    </div>
  );
}
