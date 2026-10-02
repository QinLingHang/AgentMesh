<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { ElMessage } from 'element-plus';

import { friendlyApiError } from '#/api/agentmesh';
import { useAgentMeshAuthStore } from '#/store/agentmesh-auth';

const auth = useAgentMeshAuthStore();
const route = useRoute();
const router = useRouter();

const mode = ref<'login' | 'register' | 'reset'>('login');
const loginMode = ref<'code' | 'password'>('password');
const email = ref('');
const password = ref('');
const confirmPassword = ref('');
const code = ref('');
const displayName = ref('');
const newPassword = ref('');
const passwordVisible = ref(false);
const confirmPasswordVisible = ref(false);
const newPasswordVisible = ref(false);
const busy = ref(false);
const codeBusy = ref(false);
const cooldown = ref(0);
const heroRef = ref<HTMLElement | null>(null);
let cooldownTimer: null | number = null;

function selectModeValue<T>(register: T, reset: T, login: T): T {
  if (mode.value === 'register') return register;
  if (mode.value === 'reset') return reset;
  return login;
}

const scene = computed(() =>
  selectModeValue('register', 'reset_password', 'login'),
);

const submitLabel = computed(() =>
  selectModeValue('创建 AgentMesh 账户', '重置密码', '登录 AgentMesh'),
);

const cardTitle = computed(() =>
  selectModeValue('创建账户', '重置密码', '欢迎回来'),
);

const cardHint = computed(() =>
  selectModeValue(
    '使用邮箱验证码创建你的 AgentMesh 账户。',
    '验证邮箱后设置新的登录密码。',
    '登录你的账户，继续构建和管理企业的 AI 团队。',
  ),
);

function normalizeEmail(value: string) {
  return value.trim().toLowerCase();
}

function validEmail(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function validCode(value: string) {
  return /^\d{6}$/.test(value.trim());
}

function startCooldown(seconds: number) {
  if (cooldownTimer !== null) window.clearInterval(cooldownTimer);
  cooldown.value = Math.max(1, seconds || 60);
  cooldownTimer = window.setInterval(() => {
    cooldown.value -= 1;
    if (cooldown.value <= 0 && cooldownTimer !== null) {
      window.clearInterval(cooldownTimer);
      cooldownTimer = null;
    }
  }, 1000);
}

async function sendCode() {
  const mail = normalizeEmail(email.value);
  if (!mail) return ElMessage.warning('请输入邮箱');
  if (!validEmail(mail)) return ElMessage.warning('请输入有效的邮箱地址');

  codeBusy.value = true;
  try {
    const result = await auth.requestEmailCode(mail, scene.value);
    startCooldown(result.cooldownSeconds || 60);
    ElMessage.success('验证码已发送');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '验证码发送失败'));
  } finally {
    codeBusy.value = false;
  }
}

function resolveRedirect() {
  const raw =
    typeof route.query.redirect === 'string' ? route.query.redirect : '';
  if (!raw) return '/agentmesh/workspace';

  let decoded = raw;
  for (let i = 0; i < 2; i += 1) {
    try {
      decoded = decodeURIComponent(decoded);
    } catch {
      break;
    }
  }

  if (decoded.startsWith('/agentmesh/') && decoded !== '/agentmesh/login') {
    return decoded;
  }
  return '/agentmesh/workspace';
}

async function submit() {
  const mail = normalizeEmail(email.value);
  if (!mail) return ElMessage.warning('请输入邮箱');
  if (!validEmail(mail)) return ElMessage.warning('请输入有效的邮箱地址');

  if (
    mode.value === 'login' &&
    loginMode.value === 'password' &&
    !password.value
  )
    return ElMessage.warning('请输入密码');

  if (
    mode.value === 'login' &&
    loginMode.value === 'code' &&
    !validCode(code.value)
  )
    return ElMessage.warning('请输入 6 位验证码');

  if (mode.value === 'register') {
    if (!displayName.value.trim()) return ElMessage.warning('请输入名称');
    if (password.value.length < 8)
      return ElMessage.warning('密码至少需要 8 位');
    if (confirmPassword.value !== password.value)
      return ElMessage.warning('两次输入的密码不一致');
    if (!validCode(code.value)) return ElMessage.warning('请输入 6 位验证码');
  }

  if (mode.value === 'reset') {
    if (newPassword.value.length < 8)
      return ElMessage.warning('新密码至少需要 8 位');
    if (!validCode(code.value)) return ElMessage.warning('请输入 6 位验证码');
  }

  busy.value = true;
  try {
    if (mode.value === 'login') {
      await (loginMode.value === 'password'
        ? auth.loginWithPassword(mail, password.value)
        : auth.loginWithEmailCode(mail, code.value.trim()));
      await router.replace(resolveRedirect());
      return;
    }

    if (mode.value === 'register') {
      await auth.registerAccount(
        mail,
        code.value.trim(),
        password.value,
        displayName.value.trim(),
      );
      await router.replace('/agentmesh/workspace');
      return;
    }

    await auth.changePassword(mail, code.value.trim(), newPassword.value);
    mode.value = 'login';
    loginMode.value = 'password';
    password.value = '';
    confirmPassword.value = '';
    newPassword.value = '';
    code.value = '';
    ElMessage.success('密码已重置，请重新登录');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '操作失败，请稍后重试。'));
  } finally {
    busy.value = false;
  }
}

function setMode(next: 'login' | 'register') {
  mode.value = next;
  code.value = '';
  password.value = '';
  confirmPassword.value = '';
  newPassword.value = '';
}

function onPointerMove(event: PointerEvent) {
  const el = heroRef.value;
  if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    return;
  const rect = el.getBoundingClientRect();
  const x = (event.clientX - rect.left) / rect.width - 0.5;
  const y = (event.clientY - rect.top) / rect.height - 0.5;
  el.style.setProperty('--parallax-x', `${x * 12}px`);
  el.style.setProperty('--parallax-y', `${y * 9}px`);
  el.style.setProperty('--glow-x', `${50 + x * 10}%`);
  el.style.setProperty('--glow-y', `${67 + y * 8}%`);
}

function resetParallax() {
  const el = heroRef.value;
  if (!el) return;
  el.style.setProperty('--parallax-x', '0px');
  el.style.setProperty('--parallax-y', '0px');
  el.style.setProperty('--glow-x', '50%');
  el.style.setProperty('--glow-y', '67%');
}

onBeforeUnmount(() => {
  if (cooldownTimer !== null) window.clearInterval(cooldownTimer);
});
</script>

<template>
  <main class="agentmesh-auth-v4">
    <section
      ref="heroRef"
      class="auth-hero"
      @pointermove="onPointerMove"
      @pointerleave="resetParallax"
    >
      <div class="hero-ambient hero-ambient-a"></div>
      <div class="hero-ambient hero-ambient-b"></div>
      <div class="hero-grid"></div>

      <header class="hero-brand" aria-label="AgentMesh">
        <span class="brand-logo brand-logo-large" aria-hidden="true">
          <svg viewBox="0 0 48 48" role="img">
            <circle cx="24" cy="12" r="6" />
            <circle cx="12" cy="31" r="6" />
            <circle cx="36" cy="31" r="6" />
            <path d="M21 16.8 15.2 26M27 16.8 32.8 26M18 31h12" />
          </svg>
        </span>
        <span class="brand-copy">
          <strong>AgentMesh</strong>
          <small>让 AI 团队为你工作</small>
        </span>
      </header>

      <div class="hero-copy">
        <div class="hero-badge"><span></span>企业级多智能体平台</div>
        <h1>
          让企业的 AI 团队
          <strong>协同执行，产生真实业务价值</strong>
        </h1>
        <p>
          连接智能体、知识、工具与业务系统。让复杂任务从理解、规划到执行与治理，
          始终保持可观测、可控制，为企业创造持续的业务价值。
        </p>

        <div class="feature-row" aria-label="AgentMesh 核心能力">
          <article class="feature-item">
            <span class="feature-icon">
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="5" r="2.5" />
                <circle cx="6" cy="16" r="2.5" />
                <circle cx="18" cy="16" r="2.5" />
                <path d="m10.7 7-3.3 6M13.3 7l3.3 6M8.5 16h7" />
              </svg>
            </span>
            <span><b>多智能体协作</b><small>复杂任务自动分解执行</small></span>
          </article>
          <article class="feature-item">
            <span class="feature-icon">
              <svg viewBox="0 0 24 24">
                <path
                  d="M4 5.5c3-1 5.6-.5 8 1.5v12c-2.4-2-5-2.5-8-1.5zM20 5.5c-3-1-5.6-.5-8 1.5v12c2.4-2 5-2.5 8-1.5z"
                />
              </svg>
            </span>
            <span><b>企业级 RAG</b><small>知识检索与精准引用</small></span>
          </article>
          <article class="feature-item">
            <span class="feature-icon">
              <svg viewBox="0 0 24 24">
                <path
                  d="M9.3 14.7 14.7 9.3M7.2 17.2l-1.4 1.4a3.1 3.1 0 0 1-4.4-4.4l4.2-4.2A3.1 3.1 0 0 1 10 10M16.8 6.8l1.4-1.4a3.1 3.1 0 0 1 4.4 4.4L18.4 14A3.1 3.1 0 0 1 14 14"
                />
              </svg>
            </span>
            <span><b>Tool / MCP</b><small>连接内外部工具能力</small></span>
          </article>
          <article class="feature-item">
            <span class="feature-icon">
              <svg viewBox="0 0 24 24">
                <path
                  d="M12 3 20 6v5c0 5.2-3.4 8.6-8 10-4.6-1.4-8-4.8-8-10V6z"
                />
                <path d="m8.7 12 2.1 2.1 4.6-4.7" />
              </svg>
            </span>
            <span><b>治理与可观测</b><small>权限控制与审计监控</small></span>
          </article>
        </div>
      </div>

      <div class="scene-stage" aria-hidden="true">
        <div class="scene-motion-underlay">
          <span class="scene-orbit orbit-a"></span>
          <span class="scene-orbit orbit-b"></span>
          <span class="scene-orbit orbit-c"></span>
          <span class="underlay-glow glow-a"></span>
          <span class="underlay-glow glow-b"></span>
        </div>
        <img src="/agentmesh/auth-hero-scene.png" alt="" class="scene-image" />
        <div class="scene-light-sweep"></div>
        <span class="scene-particle particle-a"></span>
        <span class="scene-particle particle-b"></span>
        <span class="scene-particle particle-c"></span>
        <span class="scene-particle particle-d"></span>
      </div>
    </section>

    <section class="auth-side">
      <div class="side-glow side-glow-top"></div>
      <div class="side-glow side-glow-bottom"></div>

      <section class="auth-card" aria-label="AgentMesh 账户">
        <div class="card-brand">
          <span class="brand-logo" aria-hidden="true">
            <svg viewBox="0 0 48 48" role="img">
              <circle cx="24" cy="12" r="6" />
              <circle cx="12" cy="31" r="6" />
              <circle cx="36" cy="31" r="6" />
              <path d="M21 16.8 15.2 26M27 16.8 32.8 26M18 31h12" />
            </svg>
          </span>
          <span class="brand-copy">
            <strong>AgentMesh</strong>
            <small>连接知识、智能体与业务</small>
          </span>
        </div>

        <div class="primary-tabs" role="tablist" aria-label="账户操作">
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'login'"
            :class="{ active: mode === 'login' }"
            @click="setMode('login')"
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'register'"
            :class="{ active: mode === 'register' }"
            @click="setMode('register')"
          >
            注册
          </button>
        </div>

        <div class="card-heading">
          <button
            v-if="mode === 'reset'"
            class="back-button"
            type="button"
            @click="setMode('login')"
          >
            ← 返回登录
          </button>
          <h2>{{ cardTitle }}</h2>
          <p>{{ cardHint }}</p>
        </div>

        <div
          v-if="mode === 'login'"
          class="login-tabs"
          role="tablist"
          aria-label="登录方式"
        >
          <button
            type="button"
            :class="{ active: loginMode === 'password' }"
            @click="loginMode = 'password'"
          >
            密码登录
          </button>
          <button
            type="button"
            :class="{ active: loginMode === 'code' }"
            @click="loginMode = 'code'"
          >
            验证码登录
          </button>
        </div>

        <form class="auth-form" novalidate @submit.prevent="submit">
          <label v-if="mode === 'register'" class="field-group">
            <span class="field-label">名称</span>
            <span class="field-shell">
              <span class="field-leading">人</span>
              <input
                v-model="displayName"
                autocomplete="name"
                placeholder="你的名称"
              />
            </span>
          </label>

          <label class="field-group">
            <span class="field-label">邮箱</span>
            <span class="field-shell">
              <span class="field-leading field-mail">□</span>
              <input
                v-model="email"
                type="email"
                autocomplete="email"
                inputmode="email"
                placeholder="name@example.com"
              />
            </span>
          </label>

          <label
            v-if="mode === 'login' && loginMode === 'password'"
            class="field-group"
          >
            <span class="field-label">密码</span>
            <span class="field-shell">
              <span class="field-leading">♙</span>
              <input
                v-model="password"
                :type="passwordVisible ? 'text' : 'password'"
                autocomplete="current-password"
                placeholder="输入密码"
              />
              <button
                class="field-action"
                type="button"
                @click="passwordVisible = !passwordVisible"
              >
                {{ passwordVisible ? '隐藏' : '显示' }}
              </button>
            </span>
          </label>

          <template v-if="mode === 'register'">
            <label class="field-group">
              <span class="field-label">密码</span>
              <span class="field-shell">
                <span class="field-leading">♙</span>
                <input
                  v-model="password"
                  :type="passwordVisible ? 'text' : 'password'"
                  autocomplete="new-password"
                  placeholder="至少 8 位密码"
                />
                <button
                  class="field-action"
                  type="button"
                  @click="passwordVisible = !passwordVisible"
                >
                  {{ passwordVisible ? '隐藏' : '显示' }}
                </button>
              </span>
            </label>

            <label class="field-group">
              <span class="field-label">确认密码</span>
              <span class="field-shell">
                <span class="field-leading">♙</span>
                <input
                  v-model="confirmPassword"
                  :type="confirmPasswordVisible ? 'text' : 'password'"
                  autocomplete="new-password"
                  placeholder="再次输入密码"
                />
                <button
                  class="field-action"
                  type="button"
                  @click="confirmPasswordVisible = !confirmPasswordVisible"
                >
                  {{ confirmPasswordVisible ? '隐藏' : '显示' }}
                </button>
              </span>
            </label>
          </template>

          <label v-if="mode === 'reset'" class="field-group">
            <span class="field-label">新密码</span>
            <span class="field-shell">
              <span class="field-leading">♙</span>
              <input
                v-model="newPassword"
                :type="newPasswordVisible ? 'text' : 'password'"
                autocomplete="new-password"
                placeholder="至少 8 位密码"
              />
              <button
                class="field-action"
                type="button"
                @click="newPasswordVisible = !newPasswordVisible"
              >
                {{ newPasswordVisible ? '隐藏' : '显示' }}
              </button>
            </span>
          </label>

          <div
            v-if="mode !== 'login' || loginMode === 'code'"
            class="field-group"
          >
            <span class="field-label">验证码</span>
            <div class="verification-row">
              <span class="field-shell">
                <span class="field-leading">#</span>
                <input
                  v-model="code"
                  maxlength="6"
                  inputmode="numeric"
                  autocomplete="one-time-code"
                  placeholder="6 位验证码"
                />
              </span>
              <button
                class="code-button"
                type="button"
                :disabled="cooldown > 0 || codeBusy"
                @click="sendCode"
              >
                {{
                  codeBusy
                    ? '发送中…'
                    : cooldown > 0
                      ? `${cooldown}s`
                      : '获取验证码'
                }}
              </button>
            </div>
          </div>

          <div v-if="mode === 'login'" class="forgot-row">
            <button type="button" @click="mode = 'reset'">忘记密码？</button>
          </div>

          <button class="submit-button" type="submit" :disabled="busy">
            <span>{{ busy ? '处理中…' : submitLabel }}</span>
            <span v-if="!busy" aria-hidden="true">→</span>
          </button>
        </form>

        <div class="auth-switch-line">
          <template v-if="mode === 'login'">
            <span>还没有账户？</span>
            <button type="button" @click="setMode('register')">创建账户</button>
          </template>
          <template v-else>
            <span>已有账户？</span>
            <button type="button" @click="setMode('login')">返回登录</button>
          </template>
        </div>

        <div class="session-line">
          <span class="session-dot"></span>
          活跃会话保持 3 天，正常使用时静默续期。
        </div>
      </section>
    </section>
  </main>
</template>

<style scoped>
.agentmesh-auth-v4 {
  --auth-primary: #6848ff;
  --auth-primary-2: #8848ff;
  --auth-blue: #2d6af6;
  --auth-text: #171b2d;
  --auth-muted: #7e879c;
  --auth-border: #e2e5ef;
  --auth-panel: #f7f5fc;

  display: grid;
  grid-template-columns: minmax(0, 1.9fr) minmax(430px, 0.95fr);
  min-height: 100vh;
  overflow: hidden;
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    'PingFang SC',
    'Microsoft YaHei',
    sans-serif;
  color: var(--auth-text);
  background: #f8f9ff;
}

.auth-hero {
  --parallax-x: 0px;
  --parallax-y: 0px;
  --glow-x: 50%;
  --glow-y: 67%;

  position: relative;
  min-width: 0;
  min-height: 100vh;
  padding: 38px clamp(48px, 5.8vw, 94px) 28px;
  overflow: hidden;
  background:
    radial-gradient(circle at 19% 7%, rgb(74 132 255 / 12%), transparent 34%),
    radial-gradient(circle at 73% 18%, rgb(139 94 255 / 14%), transparent 36%),
    linear-gradient(145deg, #fbfdff 0%, #f8f7ff 48%, #f4efff 100%);
  isolation: isolate;
}

.auth-hero::after {
  position: absolute;
  inset: 0;
  z-index: -1;
  content: '';
  background-image: radial-gradient(
    rgb(100 77 255 / 38%) 0.7px,
    transparent 0.7px
  );
  background-size: 25px 25px;
  opacity: 0.23;
  mask-image: linear-gradient(
    to bottom,
    transparent 0%,
    #000 28%,
    #000 75%,
    transparent 100%
  );
}

.hero-ambient {
  position: absolute;
  z-index: -1;
  pointer-events: none;
  border-radius: 999px;
  filter: blur(70px);
}

.hero-ambient-a {
  bottom: 9%;
  left: 41%;
  width: 360px;
  height: 360px;
  background: rgb(123 88 255 / 20%);
}

.hero-ambient-b {
  top: 8%;
  right: -5%;
  width: 280px;
  height: 280px;
  background: rgb(74 126 255 / 12%);
}

.hero-grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(rgb(112 89 255 / 8%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(112 89 255 / 8%) 1px, transparent 1px);
  background-size: 72px 72px;
  opacity: 0.18;
  mask-image: radial-gradient(circle at 55% 65%, #000 0%, transparent 64%);
}

.hero-brand,
.card-brand {
  display: flex;
  gap: 12px;
  align-items: center;
}

.hero-brand {
  position: relative;
  z-index: 5;
}

.brand-logo {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 42px;
  height: 42px;
  color: #fff;
  background: linear-gradient(145deg, #2f6df6 0%, #694cff 52%, #8b45ff 100%);
  border-radius: 13px;
  box-shadow: 0 12px 26px rgb(91 70 238 / 25%);
}

.brand-logo-large {
  width: 40px;
  height: 40px;
  color: #5663ff;
  background: transparent;
  border-radius: 12px;
  box-shadow: none;
}

.brand-logo svg {
  width: 26px;
  height: 26px;
  fill: currentcolor;
  stroke: currentcolor;
  stroke-width: 3.4;
  stroke-linecap: round;
}

.brand-logo svg circle {
  stroke: none;
}

.brand-logo svg path {
  fill: none;
}

.brand-copy strong {
  display: block;
  font-size: 21px;
  font-weight: 850;
  line-height: 1.05;
  letter-spacing: -0.03em;
}

.brand-copy small {
  display: block;
  margin-top: 4px;
  font-size: 10px;
  color: #8b92a5;
}

.hero-copy {
  position: relative;
  z-index: 4;
  width: min(100%, 900px);
  max-width: 900px;
  margin-top: clamp(42px, 5.2vh, 62px);
}

.hero-badge {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  width: fit-content;
  min-height: 30px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 800;
  color: #6349f7;
  background: rgb(255 255 255 / 78%);
  border: 1px solid #dcd5ff;
  border-radius: 999px;
  box-shadow: 0 8px 22px rgb(79 62 183 / 6%);
  backdrop-filter: blur(12px);
}

.hero-badge span {
  width: 7px;
  height: 7px;
  background: linear-gradient(135deg, #4d68ff, #8848ff);
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgb(105 76 255 / 8%);
}

.hero-copy h1 {
  max-width: 900px;
  margin: 22px 0 12px;
  font-size: clamp(42px, 3.55vw, 58px);
  font-weight: 900;
  line-height: 1.055;
  letter-spacing: -0.046em;
}

.hero-copy h1 strong {
  display: block;
  margin-top: 3px;
  font-weight: 900;
  color: transparent;
  background: linear-gradient(91deg, #2870f1 0%, #5b54f4 43%, #8745ee 100%);
  background-clip: text;
}

.hero-copy p {
  max-width: 760px;
  margin: 0;
  font-size: 14px;
  line-height: 1.74;
  color: #697389;
}

.feature-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 13px;
  width: min(100%, 820px);
  max-width: 820px;
  margin-top: 20px;
}

.feature-item {
  display: flex;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.feature-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 42px;
  height: 42px;
  color: #6848ff;
  background: rgb(255 255 255 / 86%);
  border: 1px solid rgb(104 72 255 / 13%);
  border-radius: 13px;
  box-shadow: 0 9px 22px rgb(62 47 142 / 7%);
  backdrop-filter: blur(12px);
}

.feature-icon svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentcolor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.feature-item b,
.feature-item small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feature-item b {
  font-size: 12px;
  font-weight: 850;
  color: #1f2435;
}

.feature-item small {
  margin-top: 4px;
  font-size: 9px;
  color: #9299a9;
}

/*
 * The panorama is now a real second section under the copy/features.
 * All motion is clipped inside this scene so nothing can drift over the headline.
 */
.scene-stage {
  position: relative;
  z-index: 2;
  flex: 0 0 auto;
  width: min(100%, 960px);
  aspect-ratio: 930 / 403;
  margin-top: clamp(14px, 2vh, 22px);
  overflow: hidden;
  pointer-events: none;
  background: linear-gradient(
    180deg,
    rgb(244 242 255 / 30%),
    rgb(235 232 255 / 60%)
  );
  border-radius: 28px 28px 0 0;
  box-shadow: 0 28px 65px rgb(76 58 164 / 8%);
  isolation: isolate;
  transform: translate3d(var(--parallax-x), var(--parallax-y), 0);
  transform-origin: 50% 75%;
  transition: transform 180ms ease-out;
}

.scene-motion-underlay {
  position: absolute;
  inset: -16% -8%;
  z-index: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 50% 60%, rgb(106 76 255 / 20%), transparent 34%),
    radial-gradient(circle at 26% 42%, rgb(63 121 255 / 14%), transparent 26%),
    radial-gradient(circle at 78% 48%, rgb(153 81 255 / 15%), transparent 24%);
  opacity: 0.82;
  animation: underlay-breathe 7.5s ease-in-out infinite;
}

.scene-orbit {
  position: absolute;
  top: 58%;
  left: 50%;
  border: 1px solid rgb(112 82 255 / 17%);
  border-radius: 50%;
  transform: translate(-50%, -50%) rotate(0deg);
  transform-origin: center;
}

.orbit-a {
  width: 62%;
  height: 34%;
  animation: orbit-spin 19s linear infinite;
}

.orbit-b {
  width: 76%;
  height: 43%;
  transform: translate(-50%, -50%) rotate(28deg);
  animation: orbit-spin-tilt 25s linear infinite reverse;
}

.orbit-c {
  width: 52%;
  height: 50%;
  transform: translate(-50%, -50%) rotate(-36deg);
  animation: orbit-spin-tilt-2 31s linear infinite;
}

.underlay-glow {
  position: absolute;
  border-radius: 50%;
  opacity: 0.75;
  filter: blur(24px);
}

.glow-a {
  top: 38%;
  left: 35%;
  width: 28%;
  aspect-ratio: 1;
  background: rgb(105 78 255 / 21%);
  animation: glow-drift-a 8s ease-in-out infinite;
}

.glow-b {
  top: 28%;
  right: 20%;
  width: 22%;
  aspect-ratio: 1;
  background: rgb(64 123 255 / 15%);
  animation: glow-drift-b 9.5s ease-in-out infinite;
}

.scene-image {
  position: absolute;
  inset: 0;
  z-index: 2;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  filter: saturate(1.03) contrast(1.005) brightness(1.02);
  animation: scene-breath 8s ease-in-out infinite;
}

.scene-image::selection {
  background: transparent;
}

.scene-light-sweep {
  position: absolute;
  inset: -12% -30%;
  z-index: 3;
  background: linear-gradient(
    112deg,
    transparent 31%,
    rgb(255 255 255 / 2%) 41%,
    rgb(220 214 255 / 36%) 49%,
    rgb(255 255 255 / 9%) 55%,
    transparent 66%
  );
  mix-blend-mode: screen;
  opacity: 0.34;
  transform: translateX(-36%);
  animation: light-sweep 8.8s ease-in-out infinite;
}

.scene-stage::after {
  position: absolute;
  inset: 0;
  z-index: 4;
  pointer-events: none;
  content: '';
  background: linear-gradient(
    to bottom,
    rgb(248 247 255 / 15%),
    transparent 12%
  );
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 65%);
}

.scene-particle {
  position: absolute;
  z-index: 5;
  width: 7px;
  height: 7px;
  background: #7053ff;
  border-radius: 50%;
  box-shadow: 0 0 18px #795cff;
  animation: particle-float 5s ease-in-out infinite;
}

.particle-a {
  top: 58%;
  left: 15%;
}

.particle-b {
  top: 38%;
  right: 14%;
  animation-delay: -1.4s;
}

.particle-c {
  right: 29%;
  bottom: 13%;
  animation-delay: -2.8s;
}

.particle-d {
  top: 18%;
  left: 43%;
  animation-delay: -3.8s;
}

.auth-side {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 34px clamp(28px, 3.6vw, 62px);
  overflow: hidden;
  background:
    radial-gradient(circle at 70% 17%, rgb(133 95 255 / 16%), transparent 29%),
    linear-gradient(160deg, #fafbff 0%, #f6f2ff 48%, #f8f5ff 100%);
}

.auth-side::before {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: '';
  background: linear-gradient(90deg, rgb(255 255 255 / 24%), transparent 45%);
  border-left: 1px solid rgb(128 105 210 / 8%);
}

.side-glow {
  position: absolute;
  pointer-events: none;
  border-radius: 50%;
  filter: blur(65px);
}

.side-glow-top {
  top: 6%;
  right: -80px;
  width: 260px;
  height: 260px;
  background: rgb(118 83 255 / 17%);
}

.side-glow-bottom {
  bottom: 7%;
  left: 2%;
  width: 230px;
  height: 230px;
  background: rgb(103 137 255 / 10%);
}

.auth-card {
  position: relative;
  z-index: 2;
  width: min(100%, 470px);
  padding: 29px 30px 24px;
  background: rgb(255 255 255 / 95%);
  border: 1px solid rgb(220 222 235 / 95%);
  border-radius: 25px;
  box-shadow: 0 28px 72px rgb(50 41 103 / 13%);
  backdrop-filter: blur(22px);
}

.card-brand {
  justify-content: center;
  margin-bottom: 20px;
}

.card-brand .brand-logo {
  width: 39px;
  height: 39px;
  border-radius: 12px;
}

.card-brand .brand-copy strong {
  font-size: 20px;
}

.primary-tabs,
.login-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  background: #f3f2f8;
  border-radius: 12px;
}

.primary-tabs {
  margin-bottom: 23px;
}

.primary-tabs button,
.login-tabs button {
  min-height: 39px;
  font-size: 13px;
  font-weight: 800;
  color: #70768a;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 9px;
  transition: 150ms ease;
}

.primary-tabs button:hover,
.login-tabs button:hover {
  color: #6547f5;
}

.primary-tabs button.active,
.login-tabs button.active {
  color: #6547f5;
  background: #fff;
  box-shadow: 0 6px 18px rgb(49 40 100 / 6%);
}

.card-heading {
  position: relative;
  margin-bottom: 16px;
}

.card-heading h2 {
  margin: 0;
  font-size: 27px;
  font-weight: 900;
  line-height: 1.18;
  color: #171b2d;
  letter-spacing: -0.035em;
}

.card-heading p {
  margin: 7px 0 0;
  font-size: 11px;
  line-height: 1.55;
  color: #858da0;
}

.back-button {
  padding: 0;
  margin: 0 0 10px;
  font-size: 11px;
  font-weight: 800;
  color: #6748f5;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.login-tabs {
  margin-bottom: 17px;
}

.auth-form {
  display: grid;
  gap: 13px;
}

.field-group {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.field-label {
  font-size: 12px;
  font-weight: 800;
  color: #23283a;
}

.field-shell {
  display: flex;
  gap: 10px;
  align-items: center;
  min-width: 0;
  height: 49px;
  padding: 0 13px;
  background: #fff;
  border: 1px solid #dfe3ed;
  border-radius: 11px;
  box-shadow: inset 0 1px 0 rgb(37 35 69 / 2%);
  transition:
    border-color 150ms ease,
    box-shadow 150ms ease,
    background 150ms ease;
}

.field-shell:focus-within {
  border-color: #8b76ff;
  box-shadow: 0 0 0 3px rgb(104 72 255 / 9%);
}

.field-leading {
  flex: 0 0 20px;
  width: 20px;
  font-size: 13px;
  font-weight: 800;
  color: #8992ab;
  text-align: center;
}

.field-mail {
  font-size: 0;
  line-height: 11px;
  border: 1.5px solid currentcolor;
  border-radius: 2px;
}

.field-mail::after {
  display: block;
  width: 8px;
  height: 6px;
  margin: 2px auto;
  content: '';
  border-bottom: 1px solid currentcolor;
  transform: rotate(-32deg);
}

.field-shell input {
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0;
  font-size: 13px;
  color: #252a3c;
  outline: 0;
  background: transparent;
  border: 0;
}

.field-shell input::placeholder {
  color: #b0b6c5;
}

.field-action {
  flex: 0 0 auto;
  padding: 6px 0 6px 10px;
  font-size: 11px;
  color: #858da0;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.verification-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 112px;
  gap: 9px;
}

.code-button {
  font-size: 12px;
  font-weight: 850;
  color: #6848ff;
  cursor: pointer;
  background: #f7f5ff;
  border: 1px solid #ddd9f8;
  border-radius: 11px;
  transition: 150ms ease;
}

.code-button:hover:not(:disabled) {
  background: #f1edff;
  border-color: #bcb0ff;
}

.code-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.forgot-row {
  margin-top: -3px;
  text-align: right;
}

.forgot-row button,
.auth-switch-line button {
  padding: 0;
  font-size: 11px;
  font-weight: 850;
  color: #6848ff;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.submit-button {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: center;
  height: 52px;
  margin-top: 1px;
  font-size: 14px;
  font-weight: 900;
  color: #fff;
  letter-spacing: 0.01em;
  cursor: pointer;
  background: linear-gradient(96deg, #356df6 0%, #6747f6 47%, #8b3ff0 100%);
  border: 0;
  border-radius: 11px;
  box-shadow: 0 15px 28px rgb(103 69 240 / 22%);
  transition:
    transform 150ms ease,
    box-shadow 150ms ease,
    filter 150ms ease;
}

.submit-button:hover:not(:disabled) {
  box-shadow: 0 18px 32px rgb(103 69 240 / 27%);
  filter: brightness(1.025);
  transform: translateY(-1px);
}

.submit-button:active:not(:disabled) {
  transform: translateY(0);
}

.submit-button:disabled {
  cursor: wait;
  opacity: 0.72;
}

.auth-switch-line {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  margin-top: 17px;
  font-size: 11px;
  color: #8d93a3;
}

.session-line {
  display: flex;
  gap: 7px;
  align-items: center;
  justify-content: center;
  padding-top: 18px;
  margin-top: 21px;
  font-size: 10px;
  color: #9aa1b1;
  border-top: 1px solid #edf0f5;
}

.session-dot {
  width: 7px;
  height: 7px;
  background: #28bf7a;
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgb(40 191 122 / 9%);
}

@keyframes scene-breath {
  0%,
  100% {
    transform: scale(1.002);
  }

  50% {
    transform: scale(1.018);
  }
}

@keyframes underlay-breathe {
  0%,
  100% {
    opacity: 0.66;
    transform: scale(0.98);
  }

  50% {
    opacity: 0.92;
    transform: scale(1.04);
  }
}

@keyframes orbit-spin {
  from {
    transform: translate(-50%, -50%) rotate(0deg);
  }

  to {
    transform: translate(-50%, -50%) rotate(360deg);
  }
}

@keyframes orbit-spin-tilt {
  from {
    transform: translate(-50%, -50%) rotate(28deg);
  }

  to {
    transform: translate(-50%, -50%) rotate(388deg);
  }
}

@keyframes orbit-spin-tilt-2 {
  from {
    transform: translate(-50%, -50%) rotate(-36deg);
  }

  to {
    transform: translate(-50%, -50%) rotate(324deg);
  }
}

@keyframes glow-drift-a {
  0%,
  100% {
    transform: translate3d(-10px, 4px, 0) scale(0.95);
  }

  50% {
    transform: translate3d(24px, -10px, 0) scale(1.08);
  }
}

@keyframes glow-drift-b {
  0%,
  100% {
    transform: translate3d(14px, -2px, 0) scale(1.04);
  }

  50% {
    transform: translate3d(-20px, 13px, 0) scale(0.94);
  }
}

@keyframes light-sweep {
  0%,
  24% {
    opacity: 0;
    transform: translateX(-38%);
  }

  42% {
    opacity: 0.34;
  }

  70%,
  100% {
    opacity: 0;
    transform: translateX(38%);
  }
}

@keyframes particle-float {
  0%,
  100% {
    opacity: 0.48;
    transform: translateY(0) scale(0.92);
  }

  50% {
    opacity: 0.95;
    transform: translateY(-11px) scale(1.1);
  }
}

@media (max-width: 1320px) {
  .agentmesh-auth-v4 {
    grid-template-columns: minmax(0, 1.58fr) minmax(420px, 0.92fr);
  }

  .hero-copy h1 {
    font-size: clamp(39px, 4.1vw, 54px);
  }

  .feature-row {
    gap: 8px;
  }

  .feature-icon {
    width: 38px;
    height: 38px;
  }

  .scene-stage {
    width: min(100%, 920px);
  }
}

@media (max-height: 820px) and (min-width: 1051px) {
  .hero-copy {
    margin-top: 42px;
  }

  .hero-copy h1 {
    margin-top: 18px;
    font-size: clamp(38px, 3.7vw, 54px);
  }

  .hero-copy p {
    font-size: 13px;
  }

  .feature-row {
    margin-top: 16px;
  }

  .scene-stage {
    width: min(100%, 900px);
    margin-top: 12px;
  }

  .auth-card {
    padding-block: 24px 20px;
  }
}

@media (max-width: 1050px) {
  .agentmesh-auth-v4 {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .auth-hero {
    min-height: 760px;
  }

  .auth-side {
    min-height: auto;
    padding-block: 58px 70px;
  }

  .scene-stage {
    width: min(100%, 880px);
  }
}

@media (max-width: 720px) {
  .auth-hero {
    min-height: 710px;
    padding: 26px 22px 18px;
  }

  .brand-copy strong {
    font-size: 19px;
  }

  .hero-copy {
    margin-top: 44px;
  }

  .hero-copy h1 {
    font-size: 37px;
  }

  .hero-copy p {
    font-size: 13px;
  }

  .feature-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scene-stage {
    width: calc(100% + 18px);
    margin-left: -9px;
    border-radius: 20px 20px 0 0;
  }

  .auth-side {
    padding: 28px 18px 50px;
  }

  .auth-card {
    padding: 24px 20px 21px;
    border-radius: 20px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .scene-stage {
    transform: none !important;
    transition: none;
  }

  .scene-image,
  .scene-motion-underlay,
  .scene-orbit,
  .underlay-glow,
  .scene-light-sweep,
  .scene-particle {
    animation: none !important;
  }
}

/* AGENTMESH_AUTH_LIGHT_INPUT_FIX */

/* Auth ?????????????? Vben/????????? */
.agentmesh-auth-v4 .field-shell {
  background: #fff !important;
}

.agentmesh-auth-v4 .field-shell input {
  color: #252a3c !important;
  caret-color: #6848ff;
  color-scheme: light;
  background: transparent !important;
}

/* Edge / Chrome ???? */
.agentmesh-auth-v4 .field-shell input:-webkit-autofill,
.agentmesh-auth-v4 .field-shell input:-webkit-autofill:hover,
.agentmesh-auth-v4 .field-shell input:-webkit-autofill:focus,
.agentmesh-auth-v4 .field-shell input:-webkit-autofill:active {
  caret-color: #6848ff !important;
  border: 0 !important;
  box-shadow: 0 0 0 1000px #fff inset !important;
  transition: background-color 9999s ease-out 0s;
  -webkit-text-fill-color: #252a3c !important;
}

/* ???????????????? */
.agentmesh-auth-v4 .field-shell input::selection {
  color: #252a3c;
  background: #e5dfff;
}

.agentmesh-auth-v4 .field-shell:focus-within {
  background: #fff !important;
  border-color: #8b76ff !important;
  box-shadow: 0 0 0 3px rgb(104 72 255 / 9%) !important;
}
</style>
color-scheme: light;
