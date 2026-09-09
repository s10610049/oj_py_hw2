"""Small owned styles; native widgets use Streamlit's public theme API."""

import html

import streamlit as st

CSS = """
<style>
/* R021: palette/navigation adapted from the user's PathHub demo-v3.css and
   AuthLayout.tsx. Keep our local font stack, own brand and real native widgets. */
:root {--oj-primary:#1A6B4A;--oj-primary-dark:#0F4A32;--oj-primary-soft:#EBF5F0;
  --oj-bg:#F5F5F7;--oj-surface:#FFFFFF;--oj-text:#1D1D1F;--oj-muted:#6E6E73;
  --oj-border:#E8E8ED;--oj-border-accent:#BDD7C8;--oj-border-accent-strong:#7FA68F;
  --oj-surface-tint:#F7FBF8;--oj-focus-ring:rgba(26,107,74,.13);
  --oj-ease:cubic-bezier(.2,0,0,1);}
/* Streamlit 1.63's supported minimal toolbar mode is the primary control.
   These exact framework selectors prevent a transient Deploy/menu flash while
   deliberately preserving the header and the sidebar collapse control. */
header [data-testid="stToolbar"],header [data-testid="stAppDeployButton"],#MainMenu {
  display:none;}
.oj-brand {font-size:20px;font-weight:500;color:var(--oj-text);margin:0;line-height:1.4;}
.oj-eyebrow {color:var(--oj-muted);font-size:10px;letter-spacing:.09em;margin:5px 0 0;}
.oj-meta {color:#48484A;font-size:14px;line-height:1.7;margin:8px 0 20px;}
.oj-table-scroll {overflow-x:auto;margin:12px 0 20px;border:1px solid var(--oj-border-accent);
  border-radius:12px;background:var(--oj-surface);box-shadow:0 1px 0 rgba(15,74,50,.03);}
.oj-table {width:100%; border-collapse:collapse; font-size:14px; line-height:22px;
  color:var(--oj-text); font-variant-numeric:tabular-nums;}
.oj-table th {background:#F8F9FA;font-weight:500;text-align:left;white-space:nowrap;}
.oj-table td, .oj-table th {padding:10px 14px;border-bottom:1px solid var(--oj-border);}
.oj-table td {max-width:360px; overflow-wrap:anywhere; min-width:72px;}
.oj-table td.oj-number {text-align:right;}
.oj-table tbody tr:last-child td {border-bottom:0;}
.oj-table tbody tr {transition:background-color 180ms var(--oj-ease);}
.oj-table tbody tr:hover {background:#F3F8F5;}
.oj-table-scroll:focus-visible {outline:2px solid var(--oj-primary);outline-offset:2px;}
/* Mark and changing text use separate native slots so 1s polling does not
   replace the animated mark's HTML or reannounce an unchanged live status. */
.st-key-ai_loading_surface {padding:20px 24px;min-height:132px;box-sizing:border-box;
  background:#F3F8F5;border:1px solid #D9E7DF;border-radius:16px;margin:16px 0;}
.oj-mark {color:var(--oj-primary);font:500 32px 'JetBrains Mono',monospace;display:flex;
  align-items:center; gap:3px; flex-shrink:0; }
.oj-dot {width:4px;height:4px;border-radius:50%;background:var(--oj-primary);
  animation:oj-dot 1.4s ease-in-out infinite; }
.oj-dot:nth-child(2) { animation-delay:.16s; }
.oj-dot:nth-child(3) { animation-delay:.32s; }
.oj-loading-title {font-size:16px;font-weight:500;color:var(--oj-primary-dark);}
.oj-loading-note {color:var(--oj-muted);font-size:14px;line-height:1.7;margin-top:6px;}
.oj-phrase {animation:oj-phrase-enter 200ms var(--oj-ease);}
@keyframes oj-dot { 0%,80%,100% {opacity:.35;transform:translateY(0)}
40% {opacity:1;transform:translateY(-2px)} }
@keyframes oj-phrase-enter {from{opacity:.6;transform:translateY(2px)}
  to{opacity:1;transform:translateY(0)}}
/* Streamlit 1.63 component-key scope: only code entry, never icon fonts. */
.st-key-code_editor textarea { font-family:'JetBrains Mono',Consolas,monospace;
  font-size:15px; line-height:1.6; tab-size:4; font-variant-ligatures:none; }
.st-key-problem_prose p, .st-key-problem_prose li { font-size:17px;line-height:1.76; }
.st-key-problem_prose {max-width:768px;padding-left:20px;
  border-left:2px solid var(--oj-border-accent);}
/* Native navigation buttons replace radio circles. Active state is also named
   in its accessible help and the main breadcrumb, not conveyed by color alone. */
.st-key-workspace_nav {min-height:calc(100dvh - 8rem);gap:1rem;
  animation:oj-sidebar-enter 220ms var(--oj-ease);}
.oj-sidebar-brand {display:flex;align-items:center;gap:12px;padding:2px 8px 20px;
  border-bottom:1px solid var(--oj-border);margin-bottom:2px;}
.oj-logo-symbol {color:var(--oj-primary);font:500 27px 'JetBrains Mono',monospace;}
.oj-nav-group {font-size:11px;line-height:1.5;letter-spacing:.03em;font-weight:500;
  color:var(--oj-muted);padding:18px 12px 7px;margin:0;}
.st-key-workspace_nav [class*="st-key-nav_item_"] {margin:2px 0;}
.st-key-workspace_nav [class*="st-key-nav_item_"] button,
.st-key-sidebar_account button {justify-content:flex-start;text-align:left;
  min-height:44px;padding:9px 12px;border:1px solid transparent;border-radius:10px;
  color:#48484A;background:transparent;font-weight:400;gap:10px;}
/* Streamlit 1.63's full-width inner button wrapper centers its contents.
   Scope the correction to our sidebar; main/auth actions keep native alignment. */
.st-key-workspace_nav button > div {justify-content:flex-start;text-align:left;}
.st-key-workspace_nav [class*="st-key-nav_item_"] button:hover,
.st-key-sidebar_account button:hover {background:#F0F1F2;color:var(--oj-text);}
.st-key-sidebar_account {margin-top:auto;padding-top:20px;border-top:1px solid var(--oj-border);}
.oj-sidebar-profile {display:flex;align-items:center;gap:10px;padding:0 10px 8px;}
.oj-avatar {display:flex;align-items:center;justify-content:center;width:34px;height:34px;
  border-radius:50%;background:var(--oj-primary-soft);color:var(--oj-primary);
  font-size:12px;font-weight:600;flex-shrink:0;}
.oj-profile-name {font-size:14px;font-weight:500;color:var(--oj-text);overflow-wrap:anywhere;}
.oj-profile-role {font-size:11px;color:var(--oj-muted);margin-top:2px;}
/* Stable outer workspace; route-only entry motion does not replay for polling. */
.st-key-workspace_shell {max-width:1240px;margin-inline:auto;min-height:calc(100dvh - 9rem);}
.oj-workspace-header {display:flex;align-items:center;justify-content:space-between;
  gap:16px;min-height:36px;padding-bottom:16px;margin-bottom:8px;
  border-bottom:1px solid var(--oj-border-accent);font-size:12px;color:var(--oj-muted);}
.oj-workspace-header strong {font-weight:500;color:#48484A;}
.oj-context-badge {padding:4px 10px;border:1px solid #D7E8DF;border-radius:100px;
  background:var(--oj-primary-soft);color:#436653;font-size:11px;white-space:nowrap;}
.st-key-workspace_shell h1,.st-key-workspace_shell h2,.st-key-auth_shell h1 {font-weight:500;}
.st-key-workspace_shell [data-testid="stForm"] {padding:clamp(16px,2vw,22px);
  border:1px solid var(--oj-border-accent);border-radius:16px;background:var(--oj-surface);
  box-shadow:0 1px 0 rgba(15,74,50,.025);
  transition:border-color 180ms var(--oj-ease),box-shadow 180ms var(--oj-ease);}
.st-key-workspace_shell [data-testid="stForm"]:focus-within {
  border-color:var(--oj-border-accent-strong);box-shadow:0 0 0 3px var(--oj-focus-ring);}
.st-key-workspace_shell [data-testid="stMetric"] {min-height:94px;padding:14px 16px;
  border:1px solid #DDEAE3;border-radius:14px;background:var(--oj-surface-tint);}
.st-key-workspace_shell [data-testid="stExpander"] {border-color:#D7E5DD;
  background:rgba(247,251,248,.56);}
.st-key-workspace_shell [data-baseweb="input"]:focus-within,
.st-key-workspace_shell [data-baseweb="textarea"]:focus-within,
.st-key-workspace_shell [data-baseweb="select"]:focus-within {
  border-color:var(--oj-border-accent-strong);box-shadow:0 0 0 3px var(--oj-focus-ring);}
.st-key-workspace_shell [class*="st-key-route_content_"] {
  min-height:30rem;animation:oj-route-problems 220ms var(--oj-ease);}
.st-key-workspace_shell .st-key-route_content_submissions {animation-name:oj-route-submissions;}
.st-key-workspace_shell .st-key-route_content_authoring {animation-name:oj-route-authoring;}
.st-key-workspace_shell .st-key-route_content_account {animation-name:oj-route-account;}
.st-key-workspace_shell .st-key-route_content_admin {animation-name:oj-route-admin;}
/* Authentication follows PathHub's left-green/right-form hierarchy. The
   explanatory panel has no controls and is omitted from narrow layouts. */
.st-key-auth_layout {margin:clamp(.5rem,3vh,2rem) 0 1.5rem;}
.st-key-auth_composition {max-width:100%;background:var(--oj-surface);border-radius:22px;
  border:1px solid var(--oj-border);overflow:hidden;gap:0;min-height:640px;}
.st-key-auth_story {align-self:stretch;background:var(--oj-primary-dark);
  flex:0 1 48% !important;min-width:0;}
.oj-auth-story {min-height:640px;height:100%;box-sizing:border-box;padding:40px;
  color:#FFFFFF;display:flex;flex-direction:column;justify-content:space-between;gap:32px;}
.oj-story-kicker {color:#B8D7C8;font-size:11px;letter-spacing:.1em;}
.oj-auth-story h2 {font-size:32px;line-height:1.45;font-weight:500;color:#FFFFFF;
  padding:0;margin:0 0 18px;letter-spacing:-.02em;}
.oj-auth-story p {font-size:14px;line-height:1.9;color:#C9DED3;margin:0;}
.oj-story-flow {display:flex;flex-direction:column;gap:16px;margin-top:36px;}
.oj-story-flow div {display:flex;gap:14px;align-items:center;color:#DCEBE3;font-size:13px;}
.oj-story-flow span {font:400 12px 'JetBrains Mono',monospace;color:#91BBA6;}
.oj-story-bottom {font-size:11px;color:#B8D7C8;border-top:1px solid #396A53;padding-top:20px;}
.st-key-auth_shell {max-width:100%;box-sizing:border-box;padding:32px 36px;
  background:var(--oj-surface);min-height:640px;flex:1 1 52% !important;min-width:0;}
.oj-auth-brand {display:flex;align-items:center;gap:.75rem;color:var(--oj-text);
  font-weight:500;line-height:1.5;margin:0 0 1rem;font-size:14px;}
.oj-auth-symbol {font:500 1.25rem 'JetBrains Mono',monospace;color:var(--oj-primary);}
.st-key-auth_shell h1 {font-size:26px;color:var(--oj-primary-dark);padding-top:0;}
.oj-auth-step {color:var(--oj-primary);font-size:.75rem;line-height:1.5;
  margin:.25rem 0 .5rem;letter-spacing:.01em;}
.st-key-auth_identity_row {gap:8px;}
.oj-auth-identity {display:inline-block;max-width:100%;box-sizing:border-box;
  padding:.375rem .75rem;margin:0;background:var(--oj-primary-soft);border-radius:1.5rem;
  color:var(--oj-primary);font-size:.8125rem;line-height:1.5;overflow-wrap:anywhere;}
.oj-auth-footer {color:var(--oj-muted);font-size:.75rem;line-height:1.6;margin:1rem 0 0;}
.st-key-auth_shell [class*="st-key-auth_stage_"] {
  min-height:460px;animation:oj-auth-enter 220ms var(--oj-ease);}
/* Distinct animation names make mode/step transitions animate even when React
   reuses the container DOM node; focused native controls remain interactive. */
.st-key-auth_shell .st-key-auth_stage_login_password {animation-name:oj-auth-login-password;}
.st-key-auth_shell .st-key-auth_stage_register_identity {animation-name:oj-auth-register;}
.st-key-auth_shell .st-key-auth_stage_register_password {animation-name:oj-auth-register-password;}
.st-key-auth_shell input, .st-key-auth_shell button {min-height:44px;}
.st-key-auth_shell button,.st-key-workspace_nav button,.st-key-workspace_shell button {
  transition:background-color 180ms var(--oj-ease),border-color 180ms var(--oj-ease),
    color 180ms var(--oj-ease),transform 180ms var(--oj-ease),box-shadow 180ms var(--oj-ease);}
.st-key-auth_shell button:not(:disabled):active,.st-key-workspace_nav button:not(:disabled):active,
.st-key-workspace_shell button:not(:disabled):active {transform:translateY(1px);}
.st-key-auth_shell button:focus-visible,.st-key-workspace_nav button:focus-visible,
.st-key-workspace_shell button:focus-visible {
  outline:2px solid var(--oj-primary);outline-offset:2px;}
@keyframes oj-auth-enter {from {opacity:.72;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-auth-login-password {from {opacity:.72;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-auth-register {from {opacity:.72;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-auth-register-password {from {opacity:.72;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-route-problems {from {opacity:.78;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-route-submissions {from {opacity:.78;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-route-authoring {from {opacity:.78;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-route-account {from {opacity:.78;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-route-admin {from {opacity:.78;transform:translateY(6px)}
  to {opacity:1;transform:translateY(0)}}
@keyframes oj-sidebar-enter {from {opacity:.85;transform:translateX(-4px)}
  to {opacity:1;transform:translateX(0)}}
@media (prefers-reduced-motion:reduce) {
  .oj-dot {animation:none;opacity:1;transform:none}
  .oj-phrase {display:none}
  .st-key-auth_shell [class*="st-key-auth_stage_"],
  .st-key-workspace_shell [class*="st-key-route_content_"],.st-key-workspace_nav {
    animation:none;opacity:1;transform:none;}
  .st-key-auth_shell button,.st-key-workspace_nav button,.st-key-workspace_shell button,
  .st-key-workspace_shell [data-testid="stForm"],.oj-table tbody tr {transition:none;}
  .st-key-auth_shell button:not(:disabled):active,
  .st-key-workspace_nav button:not(:disabled):active,
  .st-key-workspace_shell button:not(:disabled):active {transform:none;}
}
@media (max-width:1100px) {
  /* Streamlit 1.63 puts each keyed block inside a flex-item layout wrapper.
     Hide the story's actual flex item, not only its zero-height inner block. */
  .st-key-auth_composition > [data-testid="stLayoutWrapper"]:has(> .st-key-auth_story) {
    display:none;}
  .st-key-auth_composition > [data-testid="stLayoutWrapper"]:has(> .st-key-auth_shell) {
    flex:1 1 100%;width:100%;min-width:0;max-width:100%;}
  .st-key-auth_composition {max-width:480px;min-height:640px;}
  .st-key-auth_shell {width:100%;}
}
@media (max-width:640px) {
  .st-key-ai_loading_surface {padding:16px;gap:12px;}
  .st-key-workspace_shell {min-height:calc(100dvh - 6rem);}
  .oj-context-badge {font-size:10px;}
}
@media (max-width:480px) {
  .st-key-auth_layout {margin:.5rem 0 1rem;}
  .st-key-auth_composition {border-radius:16px;}
  .st-key-auth_shell {padding:24px 20px;}
  .oj-workspace-header {gap:8px;}
}
</style>
"""

PHRASES = (
    "先把问题说清楚，再让代码说话。",
    "边界条件，也是题目的一部分。",
    "让每个样例，都讲清一条规则。",
    "清晰的约束，成就可靠的程序。",
)


def inject():
    st.html(CSS)


def auth_story():
    st.html(
        '<section class="oj-auth-story" aria-label="编程练习室简介">'
        '<div class="oj-story-kicker">A SPACE TO THINK IN CODE</div><div>'
        "<h2>让思路成形，<br>让代码作答。</h2>"
        "<p>从读懂一道题，到写出可靠的程序。<br>把每一次思考，变成看得见的进步。</p>"
        '<div class="oj-story-flow"><div><span>01</span>阅读题目与边界</div>'
        "<div><span>02</span>编写你的解法</div>"
        "<div><span>03</span>验证与继续探索</div></div></div>"
        '<div class="oj-story-bottom">READ · CODE · REFINE</div></section>'
    )


def sidebar_brand():
    st.html(
        '<div class="oj-sidebar-brand"><span class="oj-logo-symbol" aria-hidden="true">'
        '{ }</span><div><p class="oj-brand">编程练习室</p>'
        '<p class="oj-eyebrow">OJ WORKSPACE</p></div></div>'
    )


def active_navigation(slug):
    # Change only the selected style, never the button/container identity. This
    # keeps native keyboard focus attached while moving between route pages.
    if slug not in {"problems", "submissions", "authoring", "account", "admin"}:
        raise ValueError("Unknown navigation target")
    selector = f".st-key-workspace_nav .st-key-nav_item_{slug} button"
    st.html(
        "<style>" + selector + "{background:var(--oj-primary-soft);"
        "color:var(--oj-primary);font-weight:600;border-color:#D9E9E0;}"
        + selector
        + ":hover{background:#E2F0E8;color:var(--oj-primary-dark);}</style>"
    )


def sidebar_profile(name, role):
    st.html(
        '<div class="oj-sidebar-profile"><span class="oj-avatar" aria-hidden="true">'
        + html.escape(str(name).strip()[:2].upper())
        + '</span><div><div class="oj-profile-name">'
        + html.escape(str(name))
        + '</div><div class="oj-profile-role">'
        + html.escape(str(role))
        + "</div></div></div>"
    )


def workspace_header(page, role):
    st.html(
        '<div class="oj-workspace-header"><span>工作台 &nbsp;/&nbsp; <strong>'
        + html.escape(str(page))
        + '</strong></span><span class="oj-context-badge">'
        + html.escape(str(role))
        + "</span></div>"
    )


def auth_identity(name):
    st.html('<p class="oj-auth-identity">' + html.escape(str(name)) + "</p>")


def loading(progress, elapsed):
    # These values are escaped before insertion. They never determine task status.
    elapsed = max(0, float(elapsed or 0))
    phrase = PHRASES[int(elapsed // 10) % len(PHRASES)]
    with st.container(key="ai_loading_surface", horizontal=True, vertical_alignment="center"):
        with st.container(key="ai_loading_mark", width=64):
            st.html(
                '<div class="oj-mark" aria-hidden="true">{<span class="oj-dot"></span>'
                '<span class="oj-dot"></span><span class="oj-dot"></span>}</div>'
            )
        with st.container(key="ai_loading_copy", gap=None):
            st.html(
                '<div class="oj-loading-title" role="status" aria-live="polite">'
                + html.escape(str(progress or "正在等待任务更新"))
                + "</div>"
            )
            st.html('<div class="oj-loading-note">已耗时 ' + f"{elapsed:.0f} 秒</div>")
            st.html(
                '<div class="oj-loading-note oj-phrase" aria-hidden="true">' + phrase + "</div>"
            )
