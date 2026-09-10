"""Small owned styles; native widgets use Streamlit's public theme API."""

import html

import streamlit as st

from frontend.i18n import t

CSS = """
<style>
/* R021: palette/navigation adapted from the user's PathHub demo-v3.css and
   AuthLayout.tsx. Keep our local font stack, own brand and real native widgets. */
:root {--oj-primary:#1A6B4A;--oj-primary-dark:#0F4A32;--oj-primary-soft:#EBF5F0;
  --oj-bg:#F5F5F7;--oj-surface:#FFFFFF;--oj-text:#1D1D1F;--oj-muted:#6E6E73;
  --oj-border:#E8E8ED;--oj-border-accent:#BDD7C8;--oj-border-accent-strong:#7FA68F;
  --oj-surface-tint:#F7FBF8;--oj-focus-ring:rgba(26,107,74,.13);
  --oj-success:#187A55;--oj-danger:#C13D3D;--oj-warning:#A76500;--oj-info:#3468A5;
  --oj-ease:cubic-bezier(.2,0,0,1);}
/* Keep Streamlit's toolbar host mounted: in the collapsed state it owns the
   only native button that can reopen the sidebar. Hide only deploy/menu UI. */
header [data-testid="stToolbar"] {display:flex;align-items:center;}
header [data-testid="stAppDeployButton"],#MainMenu {display:none;}
.st-key-auth_language_bar {min-height:40px;margin-bottom:2px;}
.st-key-workspace_commandbar {position:relative;z-index:20;padding-bottom:12px;
  margin-bottom:10px;border-bottom:1px solid var(--oj-border-accent);}
.st-key-workspace_header_slot {min-width:0;}
.st-key-workspace_actions {width:max-content;min-width:max-content;margin-left:auto;}
.st-key-workspace_actions > [data-testid="stLayoutWrapper"] {flex:0 0 auto!important;
  width:max-content!important;}
.oj-command-identity {display:flex;align-items:center;gap:8px;min-height:36px;
  padding:3px 10px 3px 4px;
  border:1px solid #D7E8DF;border-radius:999px;background:var(--oj-primary-soft);color:#436653;}
.oj-command-avatar {display:grid;place-items:center;width:28px;height:28px;border-radius:50%;
  background:var(--oj-primary);color:#FFFFFF;font-size:10px;font-weight:600;letter-spacing:.02em;}
.oj-command-identity strong {display:block;max-width:112px;overflow:hidden;text-overflow:ellipsis;
  color:#294D3D;font-size:11px;font-weight:600;line-height:1.2;white-space:nowrap;}
.oj-command-identity small {display:block;margin-top:2px;color:#5F786C;font-size:9px;
  line-height:1.1;}
.st-key-language_control,.st-key-chat_launcher {display:flex;align-items:center;width:max-content;
  min-height:40px;margin-bottom:0;}
.st-key-language_control [data-testid="stButton"],
.st-key-chat_launcher [data-testid="stButton"] {border:0!important;background:transparent!important;
  box-shadow:none!important;}
.st-key-language_control button,.st-key-chat_launcher button {box-sizing:border-box;height:36px;
  min-height:36px;padding:0 14px;border-radius:999px;line-height:1;outline:0!important;}
.st-key-language_control button {white-space:nowrap;color:var(--oj-primary);
  border:1px solid var(--oj-border-accent)!important;background:#FAFCFB!important;
  box-shadow:none!important;transition:border-color 180ms var(--oj-ease),
  background 180ms var(--oj-ease),box-shadow 180ms var(--oj-ease);}
.st-key-language_control button:hover {border-color:var(--oj-border-accent-strong);
  background:var(--oj-primary-soft)!important;}
.st-key-language_control button:focus-visible {border-color:var(--oj-primary)!important;
  box-shadow:0 0 0 3px var(--oj-focus-ring)!important;}
.st-key-chat_launcher button {white-space:nowrap;border:1px solid #16754F!important;
  background:var(--oj-primary)!important;color:#FFFFFF;
  box-shadow:0 5px 16px rgba(15,74,50,.14);transition:transform 180ms var(--oj-ease),
  background 180ms var(--oj-ease),box-shadow 180ms var(--oj-ease);}
.st-key-chat_launcher button:hover {background:var(--oj-primary-dark)!important;color:#FFFFFF;
  transform:translateY(-1px);box-shadow:0 8px 22px rgba(15,74,50,.2);}
.st-key-chat_launcher button:active {transform:translateY(0) scale(.985);}
.st-key-chat_launcher button:focus-visible {box-shadow:0 0 0 3px var(--oj-focus-ring),
  0 5px 16px rgba(15,74,50,.14)!important;}
.st-key-chat_launcher button p {display:inline-flex;align-items:center;gap:7px;}
.st-key-chat_launcher button p::before {content:"";display:inline-block;width:18px;height:18px;
  flex:0 0 18px;border-radius:50%;background:url("app/static/brand/ai-chat-avatar.png")
  center/cover no-repeat;box-shadow:0 0 0 1px rgba(255,255,255,.22);}

/* PathHub-inspired assistant structure, implemented in Streamlit. */
[data-testid="stDialog"]:has(.oj-chat-drawer-marker) {padding:0!important;
  align-items:stretch!important;justify-content:flex-end!important;
  background:rgba(7,18,13,.30)!important;overflow:hidden!important;
  transition:background 200ms var(--oj-ease),display 200ms allow-discrete,
    overlay 200ms allow-discrete;}
[data-testid="stDialog"]:has(.oj-chat-drawer-marker) [role="dialog"] {
  position:absolute!important;inset:0 0 0 auto!important;width:min(480px,100vw)!important;
  max-width:100vw!important;height:100dvh!important;max-height:100dvh!important;margin:0!important;
  padding:0!important;border:0!important;border-radius:24px 0 0 24px!important;
  background:#FBFCFB!important;box-shadow:-22px 0 54px rgba(9,35,24,.18)!important;
  overflow:hidden!important;animation:oj-chat-enter 200ms var(--oj-ease) both;
  transition:width 200ms var(--oj-ease),border-radius 200ms var(--oj-ease),
    transform 200ms var(--oj-ease),opacity 200ms var(--oj-ease);}
[data-testid="stDialog"]:has(.st-key-chat_drawer_fullscreen) [role="dialog"] {
  width:100vw!important;border-radius:0!important;}
[data-testid="stDialog"]:has(.oj-chat-drawer-marker) [role="dialog"] > div {
  height:100%!important;max-height:100%!important;overflow:hidden!important;}
.st-key-chat_drawer,.st-key-chat_drawer_fullscreen {height:100%;min-height:0;
  overflow:hidden;padding:0 18px 16px;}
.st-key-chat_drawer_toolbar {position:sticky;top:0;z-index:5;min-height:64px;
  padding:10px 0;border-bottom:1px solid var(--oj-border);background:rgba(251,252,251,.94);
  backdrop-filter:blur(16px);}
.st-key-chat_drawer_toolbar p {margin:0;color:var(--oj-muted);font-size:12px;}
.st-key-chat_drawer_toolbar button {border-radius:10px;min-height:34px;}
.st-key-chat_conversation_panel,.st-key-chat_history_panel {min-width:0;min-height:0;
  height:calc(100dvh - 94px);overflow:hidden;}
.st-key-chat_history_panel {border-right:1px solid var(--oj-border);padding-right:12px;
  overflow-y:auto;scrollbar-width:thin;}
.st-key-chat_messages {min-height:180px;height:calc(100dvh - 252px)!important;
  overflow-y:auto;padding:12px 2px 8px;scrollbar-width:thin;scroll-behavior:smooth;}
.st-key-chat_composer {position:sticky;bottom:0;z-index:4;padding-top:8px;
  border-top:1px solid #EEF2EF;background:#FBFCFB;}
.st-key-chat_composer textarea {border-color:var(--oj-border-accent);border-radius:14px;}
.st-key-chat_composer button {border-radius:12px;background:var(--oj-primary);}
.oj-chat-avatar-slot {display:inline-grid;place-items:center;width:30px;height:30px;
  overflow:hidden;border-radius:50%;border:1px solid rgba(22,117,79,.20);
  background:#0F4A32;box-shadow:0 3px 10px rgba(15,74,50,.14);vertical-align:middle;}
.oj-chat-avatar-slot img {display:block;width:100%;height:100%;object-fit:cover;}
.oj-chat-avatar-header {width:34px;height:34px;flex:0 0 34px;}
.oj-chat-avatar-loading {width:28px;height:28px;}
.st-key-chat_messages [data-testid="stChatMessageAvatarContainer"] img {
  border-radius:50%;box-shadow:0 2px 8px rgba(15,74,50,.12);}
.st-key-chat_loading {display:flex;align-items:center;gap:9px;padding:10px 0;}
.oj-chat-loading {display:flex;align-items:center;gap:9px;min-height:34px;padding:7px 12px;
  border:1px solid #DDE9E2;border-radius:14px;background:#F2F7F4;color:#355548;}
.oj-chat-loading-spinner {display:block;width:16px;height:16px;box-sizing:border-box;
  flex:0 0 16px;border:2px solid #B7D5C6;border-top-color:var(--oj-primary);
  border-radius:50%;animation:oj-chat-spin 700ms linear infinite;}
.oj-chat-loading-phrases {position:relative;display:block;width:11em;height:20px;
  overflow:hidden;font-size:13px;line-height:20px;}
.oj-chat-loading-phrase {position:absolute;inset:0;opacity:0;white-space:nowrap;
  animation:oj-chat-phrase 2.1s linear infinite;}
.oj-chat-loading-phrase:nth-child(2) {animation-delay:.7s;}
.oj-chat-loading-phrase:nth-child(3) {animation-delay:1.4s;}
.oj-chat-stream-cursor {display:inline-block;width:2px;height:1em;margin-left:3px;
  border-radius:2px;background:var(--oj-primary);vertical-align:-.12em;
  animation:oj-chat-cursor 820ms steps(1,end) infinite;}

/* AI authoring progress is stage-driven by the backend, never elapsed-time driven. */
.st-key-ai_generation_progress {margin:4px 0 10px;}
.oj-stage-progress {display:grid;gap:7px;width:100%;}
.oj-stage-progress-head {display:flex;align-items:center;justify-content:space-between;
  gap:12px;color:#476257;font-size:12px;font-weight:550;line-height:1.3;}
.oj-stage-progress-head strong {color:var(--oj-primary);font-variant-numeric:tabular-nums;
  font-size:13px;font-weight:700;}
.oj-stage-progress-track {height:8px;width:100%;border-radius:999px;
  background:#E2EEE8;box-shadow:inset 0 0 0 1px rgba(15,74,50,.06);overflow:hidden;}
.oj-stage-progress-track > span {display:block;height:100%;border-radius:inherit;
  background:var(--oj-primary);transition:width 240ms var(--oj-ease);}

@keyframes oj-chat-enter {from{opacity:0;transform:translateX(28px)}
  to{opacity:1;transform:translateX(0)}}
@keyframes oj-chat-exit {from{opacity:1;transform:translateX(0)}
  to{opacity:0;transform:translateX(28px)}}
[data-testid="stDialog"]:has(.oj-chat-drawer-marker.is-closing) {
  background:rgba(7,18,13,0)!important;}
[data-testid="stDialog"]:has(.oj-chat-drawer-marker.is-closing) [role="dialog"] {
  animation:oj-chat-exit 200ms var(--oj-ease) both;}
@keyframes oj-chat-spin {to{transform:rotate(360deg)}}
@keyframes oj-chat-phrase {0%{opacity:0;transform:translateY(2px)}
  7%{opacity:1;transform:translateY(0)} 27.6%{opacity:1;transform:translateY(0)}
  33.3%,100%{opacity:0;transform:translateY(-2px)}}
@keyframes oj-chat-cursor {0%,52%{opacity:1} 53%,100%{opacity:0}}
@starting-style {
  [data-testid="stDialog"]:has(.oj-chat-drawer-marker) {background:rgba(7,18,13,0)!important;}
  [data-testid="stDialog"]:has(.oj-chat-drawer-marker) [role="dialog"] {
    opacity:0;transform:translateX(28px);}
}
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
/* Personal progress: compact OJ semantics with text labels as well as color. */
.st-key-workspace_shell [class*="st-key-catalog_problem_"] {
  padding:14px 16px;margin:10px 0;border:1px solid var(--oj-border-accent);
  border-radius:14px;background:var(--oj-surface);box-shadow:0 1px 0 rgba(15,74,50,.025);
  transition:border-color 180ms var(--oj-ease),box-shadow 180ms var(--oj-ease),
    transform 180ms var(--oj-ease);}
.st-key-workspace_shell [class*="st-key-catalog_problem_"]:hover {
  border-color:var(--oj-border-accent-strong);box-shadow:0 8px 24px rgba(15,74,50,.055);
  transform:translateY(-1px);}
.oj-catalog-badges {display:flex;align-items:flex-end;justify-content:center;
  flex-direction:column;gap:6px;min-width:0;}
.oj-status-token,.oj-difficulty-token,.oj-state-token {display:inline-flex;align-items:center;
  max-width:100%;
  width:max-content;padding:3px 9px;border:1px solid var(--oj-token-border,#D7DDDA);
  border-radius:999px;background:var(--oj-token-bg,#F1F3F2);color:var(--oj-token,#5E6561);
  font-size:11px;font-weight:500;line-height:1.45;overflow-wrap:anywhere;}
.status-ac {--oj-token:#126A49;--oj-token-bg:#E7F5EE;--oj-token-border:#B9DECB;}
.status-failed,.status-runtime {--oj-token:#A93333;--oj-token-bg:#FCEEEE;
  --oj-token-border:#EFC8C8;}
.status-partial,.status-outdated,.status-timeout,.status-memory {
  --oj-token:#935C00;--oj-token-bg:#FFF5E4;--oj-token-border:#EED5A9;}
.status-compile,.status-judge-error {--oj-token:#2C5F9A;--oj-token-bg:#EDF4FC;
  --oj-token-border:#C7D9EE;}
.status-pending {--oj-token:#42647E;--oj-token-bg:#EFF4F7;--oj-token-border:#CFDCE4;}
.status-unattempted,.status-unavailable {--oj-token:#686D6A;--oj-token-bg:#F3F4F4;
  --oj-token-border:#DCDDDE;}
.state-passed {--oj-token:#126A49;--oj-token-bg:#E7F5EE;--oj-token-border:#B9DECB;}
.state-failed {--oj-token:#A93333;--oj-token-bg:#FCEEEE;--oj-token-border:#EFC8C8;}
.state-partial,.state-outdated {--oj-token:#935C00;--oj-token-bg:#FFF5E4;
  --oj-token-border:#EED5A9;}
.state-pending {--oj-token:#42647E;--oj-token-bg:#EFF4F7;--oj-token-border:#CFDCE4;}
.state-unattempted {--oj-token:#686D6A;--oj-token-bg:#F3F4F4;
  --oj-token-border:#DCDDDE;}
.difficulty-red {--oj-token:#B43B42;--oj-token-bg:#FCEEEF;--oj-token-border:#EEC8CB;}
.difficulty-orange {--oj-token:#A55812;--oj-token-bg:#FFF2E7;--oj-token-border:#EACDB3;}
.difficulty-yellow {--oj-token:#806313;--oj-token-bg:#FFF9DB;--oj-token-border:#E7D98E;}
.difficulty-green {--oj-token:#14704F;--oj-token-bg:#E9F6EF;--oj-token-border:#BBDDCB;}
.difficulty-cyan {--oj-token:#176B75;--oj-token-bg:#EAF7F8;--oj-token-border:#B9DEE1;}
.difficulty-blue {--oj-token:#315E9E;--oj-token-bg:#EDF3FC;--oj-token-border:#C5D6EF;}
.difficulty-purple {--oj-token:#7048A0;--oj-token-bg:#F5EFFB;--oj-token-border:#D9C9EA;}
.difficulty-black {--oj-token:#343438;--oj-token-bg:#EEEEF0;--oj-token-border:#CACAD0;}
.difficulty-neutral {--oj-token:#686D6A;--oj-token-bg:#F3F4F4;--oj-token-border:#DCDDDE;}
/* Analytics markup is framework-independent and responsive without a chart library. */
.oj-analytics-kpis {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;
  margin:18px 0 28px;}
.oj-analytics-kpi {min-width:0;min-height:96px;box-sizing:border-box;padding:15px 16px;
  border:1px solid #DCE9E2;border-radius:14px;background:var(--oj-surface-tint);}
.oj-analytics-kpi:first-child {border-color:var(--oj-border-accent-strong);
  background:#F1F8F4;}
.oj-analytics-kpi-label {display:block;color:var(--oj-muted);font-size:12px;line-height:1.5;
  margin-bottom:9px;}
.oj-analytics-kpi-value {color:var(--oj-text);font-size:clamp(20px,2.2vw,28px);
  font-weight:500;line-height:1.15;font-variant-numeric:tabular-nums;letter-spacing:-.02em;}
.oj-analytics-kpi-unit {color:var(--oj-muted);font-size:11px;margin-left:6px;}
.oj-chart,.oj-panel,.oj-analytics-table-wrap {box-sizing:border-box;border:1px solid
  var(--oj-border-accent);border-radius:16px;background:var(--oj-surface);}
.oj-chart {padding:14px 16px;margin:10px 0 22px;overflow:hidden;}
.oj-timeline svg {display:block;max-width:100%;font-family:'Noto Sans SC',system-ui,sans-serif;}
.oj-timeline-image {display:block;width:100%;height:240px;object-fit:contain;}
.oj-timeline-axis {fill:var(--oj-muted);font-size:11px;font-variant-numeric:tabular-nums;}
.oj-timeline-points circle {stroke:#FFFFFF;stroke-width:2;outline:none;}
.oj-timeline-points circle:focus {stroke:var(--oj-primary-dark);stroke-width:3;}
.oj-chart-empty {box-sizing:border-box;margin:10px 0;padding:24px;border:1px dashed
  var(--oj-border-accent);border-radius:12px;color:var(--oj-muted);font-size:13px;
  text-align:center;background:var(--oj-surface-tint);}
.oj-analytics-grid {display:grid;gap:14px;margin:14px 0;}
.oj-analytics-grid-two {grid-template-columns:repeat(2,minmax(0,1fr));}
.oj-panel {min-width:0;padding:18px;}
.oj-panel-knowledge {margin:14px 0 24px;}
.oj-panel h3 {font-size:15px;font-weight:500;margin:0 0 16px;color:var(--oj-text);}
.oj-bar-list {display:flex;flex-direction:column;gap:14px;}
.oj-bar-row {min-width:0;}
.oj-bar-meta {display:flex;align-items:center;justify-content:space-between;gap:12px;
  min-width:0;margin-bottom:7px;color:var(--oj-muted);font-size:11px;}
.oj-bar-meta > span:last-child {white-space:nowrap;font-variant-numeric:tabular-nums;}
.oj-bar-track {height:6px;overflow:hidden;border-radius:999px;background:#ECEFED;}
.oj-bar-fill {display:block;height:100%;border-radius:inherit;background:var(--oj-token,#1A6B4A);}
.outcome-pending {--oj-token:#607D91;}
.outcome-judge_error {--oj-token:#4271A8;}
.outcome-zero_score {--oj-token:#C14B4B;}
.outcome-partial {--oj-token:#BB780C;}
.outcome-full {--oj-token:#187A55;}
.knowledge-mastery {--oj-token:#238363;}
.oj-analytics-table-wrap {overflow:auto;margin:10px 0 24px;}
.oj-analytics-table {width:100%;min-width:720px;border-collapse:collapse;color:var(--oj-text);
  font-size:13px;line-height:1.55;}
.oj-analytics-table th,.oj-analytics-table td {padding:12px 14px;text-align:left;
  border-bottom:1px solid var(--oj-border);vertical-align:middle;}
.oj-analytics-table thead th {position:sticky;top:0;background:#F7F9F8;color:#555B58;
  font-size:11px;font-weight:500;white-space:nowrap;}
.oj-analytics-table tbody tr:last-child > * {border-bottom:0;}
.oj-analytics-table tbody tr {transition:background-color 180ms var(--oj-ease);}
.oj-analytics-table tbody tr:hover {background:#F4F8F6;}
.oj-analytics-table tbody th {font-weight:400;min-width:180px;}
.oj-problem-id {display:block;color:var(--oj-muted);font:500 10px 'JetBrains Mono',monospace;
  margin-bottom:2px;}
.oj-problem-title {display:block;overflow-wrap:anywhere;}
.oj-problem-tags {max-width:260px;overflow-wrap:anywhere;color:#555B58;}
.oj-number {font-variant-numeric:tabular-nums;white-space:nowrap;}
.oj-sr-only {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.oj-analytics-table-wrap:focus-visible {outline:2px solid var(--oj-primary);outline-offset:2px;}
/* Admin cohort overview: compact operational cards and comparison charts. */
.oj-admin-kpis {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;
  margin:16px 0 18px;}
.oj-admin-kpi {box-sizing:border-box;min-width:0;min-height:92px;padding:15px 16px;
  border:1px solid #DDE8E2;border-radius:14px;background:#FFFFFF;}
.oj-admin-kpi:first-child {border-color:#B8D8C7;background:#F1F8F4;}
.oj-admin-kpi span {display:block;color:var(--oj-muted);font-size:11px;margin-bottom:9px;}
.oj-admin-kpi strong {color:var(--oj-text);font-size:26px;font-weight:500;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em;}
.oj-admin-kpi small {color:var(--oj-muted);font-size:10px;margin-left:5px;}
.oj-admin-chart-grid {display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);
  gap:14px;margin:14px 0 24px;}
.oj-admin-comparison,.oj-admin-outcomes {min-width:0;box-sizing:border-box;padding:18px;
  border:1px solid var(--oj-border-accent);border-radius:16px;background:#FFFFFF;}
.oj-admin-comparison > header,.oj-admin-outcomes > header {display:flex;align-items:flex-start;
  justify-content:space-between;gap:14px;margin-bottom:17px;}
.oj-admin-comparison h3,.oj-admin-outcomes h3 {margin:0 0 4px;color:var(--oj-text);
  font-size:15px;font-weight:500;}
.oj-admin-comparison header p,.oj-admin-outcomes header p {margin:0;color:var(--oj-muted);
  font-size:10px;line-height:1.5;}
.oj-admin-legend,.oj-admin-outcome-legend {display:flex;flex-wrap:wrap;justify-content:flex-end;
  gap:7px;color:var(--oj-muted);font-size:9px;white-space:nowrap;}
.oj-admin-legend span,.oj-admin-outcome-legend span {display:inline-flex;align-items:center;
  gap:4px;}
.oj-admin-legend span::before,.oj-admin-outcome-legend span::before {content:"";
  width:7px;height:7px;border-radius:50%;background:var(--oj-outcome,#9AA6A0);}
.oj-admin-legend .score {--oj-outcome:#1A6B4A;}
.oj-admin-legend .pass {--oj-outcome:#5A78A4;}
.oj-admin-comparison-scroll,.oj-admin-outcomes-scroll {display:flex;flex-direction:column;
  gap:13px;max-height:380px;overflow:auto;padding-right:4px;scrollbar-width:thin;}
.oj-admin-compare-row {display:grid;grid-template-columns:minmax(88px,128px) minmax(110px,1fr) 64px;
  align-items:center;gap:10px;}
.oj-admin-compare-person {min-width:0;}
.oj-admin-compare-person strong {display:block;overflow:hidden;text-overflow:ellipsis;
  font-size:11px;font-weight:500;white-space:nowrap;}
.oj-admin-compare-person span {display:block;color:var(--oj-muted);font-size:9px;margin-top:2px;}
.oj-admin-compare-bars,.oj-admin-compare-values {display:grid;gap:4px;}
.oj-admin-compare-bars > div {height:6px;overflow:hidden;border-radius:999px;background:#EDF1EF;}
.oj-admin-bar {display:block;height:100%;border-radius:inherit;}
.oj-admin-bar.score {background:#1A6B4A;}
.oj-admin-bar.pass {background:#5A78A4;}
.oj-admin-compare-values {color:var(--oj-muted);font-size:9px;text-align:right;
  font-variant-numeric:tabular-nums;}
.oj-admin-outcome-row {display:grid;grid-template-columns:minmax(72px,110px) minmax(110px,1fr) 26px;
  align-items:center;gap:9px;color:var(--oj-muted);font-size:9px;}
.oj-admin-outcome-row strong {overflow:hidden;text-overflow:ellipsis;color:var(--oj-text);
  font-size:11px;font-weight:500;white-space:nowrap;}
.oj-admin-outcome-track {display:flex;height:9px;overflow:hidden;border-radius:999px;
  background:#EDF1EF;}
.oj-admin-outcome-track > span {display:block;height:100%;background:var(--oj-outcome,#CAD2CE);}
.oj-admin-outcome-track .outcome-empty {width:100%;background:#EDF1EF;}
.outcome-accepted {--oj-outcome:#1A7A52;}
.outcome-partial {--oj-outcome:#D08A1E;}
.outcome-wrong_answer {--oj-outcome:#D25454;}
.outcome-compile_error {--oj-outcome:#526A9A;}
.outcome-time_limit {--oj-outcome:#8D5D9B;}
.outcome-memory_limit {--oj-outcome:#7A607F;}
.outcome-runtime_error {--oj-outcome:#A64A69;}
.outcome-judge_error {--oj-outcome:#56717F;}
.outcome-pending {--oj-outcome:#9AA6A0;}
.oj-admin-account-table-wrap {overflow:auto;margin:10px 0 24px;border:1px solid
  var(--oj-border-accent);border-radius:16px;background:#FFFFFF;}
.oj-admin-account-table {width:100%;min-width:1040px;border-collapse:collapse;color:var(--oj-text);
  font-size:12px;line-height:1.5;}
.oj-admin-account-table th,.oj-admin-account-table td {padding:11px 12px;text-align:left;
  border-bottom:1px solid var(--oj-border);vertical-align:middle;}
.oj-admin-account-table thead th {position:sticky;top:0;background:#F7F9F8;color:#555B58;
  font-size:10px;font-weight:500;white-space:nowrap;}
.oj-admin-account-table tbody tr:last-child > * {border-bottom:0;}
.oj-admin-account-table tbody tr:hover {background:#F4F8F6;}
.oj-admin-account-table tbody th strong {display:block;font-size:12px;font-weight:500;}
.oj-admin-account-table tbody th small {display:block;color:var(--oj-muted);font-size:9px;
  font-weight:400;margin-top:2px;}
.oj-account-status {display:inline-flex;padding:3px 8px;border:1px solid #BFE0CF;
  border-radius:999px;background:#EAF6F0;color:#176849;font-size:9px;white-space:nowrap;}
.oj-account-status.disabled {border-color:#E7C8C8;background:#FBEFEF;color:#A23A3A;}
.oj-admin-account-table-wrap:focus-visible {outline:2px solid var(--oj-primary);
  outline-offset:2px;}
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
.oj-logo-image {display:block;width:38px;height:38px;object-fit:contain;flex-shrink:0;}
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
.oj-workspace-header {display:flex;align-items:center;gap:16px;min-height:36px;
  font-size:12px;color:var(--oj-muted);}
.oj-workspace-header strong {font-weight:500;color:#48484A;}
.st-key-workspace_shell h1,.st-key-workspace_shell h2,.st-key-auth_shell h1 {font-weight:500;}
.st-key-workspace_shell [data-testid="stForm"] {padding:clamp(16px,2vw,22px);
  border:1px solid var(--oj-border-accent);border-radius:16px;background:var(--oj-surface);
  box-shadow:0 1px 0 rgba(15,74,50,.025);
  transition:border-color 180ms var(--oj-ease),box-shadow 180ms var(--oj-ease);}
.st-key-workspace_shell [data-testid="stForm"]:focus-within {
  border-color:var(--oj-border-accent-strong);box-shadow:0 0 0 3px var(--oj-focus-ring);}
.st-key-workspace_shell [data-testid="stMetric"] {min-height:94px;padding:14px 16px;
  border:1px solid #DDEAE3;border-radius:14px;background:var(--oj-surface-tint);}
.st-key-route_content_authoring [data-testid="stMetricValue"] {
  font-size:clamp(1.3rem,2vw,1.72rem);letter-spacing:-.025em;white-space:nowrap;}
.st-key-route_content_authoring [data-testid="stHorizontalBlock"] >
  [data-testid="stColumn"]:last-child [data-testid="stMetricValue"] {
  font-size:clamp(1.1rem,1.5vw,1.35rem);letter-spacing:-.035em;}
.st-key-workspace_shell [data-testid="stExpander"] {border-color:#D7E5DD;
  background:rgba(247,251,248,.56);}
.st-key-workspace_shell [data-baseweb="input"]:focus-within,
.st-key-workspace_shell [data-baseweb="textarea"]:focus-within,
.st-key-workspace_shell [data-baseweb="select"]:focus-within {
  border-color:var(--oj-border-accent-strong);box-shadow:0 0 0 3px var(--oj-focus-ring);}
.st-key-workspace_shell [class*="st-key-route_content_"] {
  min-height:30rem;animation:oj-route-problems 220ms var(--oj-ease);}
.st-key-workspace_shell .st-key-route_content_submissions {animation-name:oj-route-submissions;}
.st-key-workspace_shell .st-key-route_content_analytics {animation-name:oj-route-analytics;}
.st-key-workspace_shell .st-key-route_content_authoring {animation-name:oj-route-authoring;}
.st-key-workspace_shell .st-key-route_content_account {animation-name:oj-route-account;}
.st-key-workspace_shell .st-key-route_content_admin {animation-name:oj-route-admin;}
/* Authentication follows PathHub's left-green/right-form hierarchy. The
   explanatory panel has no controls and is omitted from narrow layouts. */
.st-key-auth_layout {margin:clamp(.5rem,3vh,2rem) 0 1.5rem;}
.st-key-auth_composition {max-width:100%;margin-inline:auto!important;
  background:var(--oj-surface);border-radius:22px;
  border:1px solid var(--oj-border);overflow:hidden;gap:0;min-height:640px;}
.st-key-auth_story {align-self:stretch;background:var(--oj-primary-dark);
  flex:0 1 48% !important;min-width:0;}
.oj-auth-story {min-height:640px;height:100%;box-sizing:border-box;padding:40px;
  color:#FFFFFF;display:flex;flex-direction:column;justify-content:space-between;gap:32px;}
.oj-auth-story-brand {display:flex;align-items:flex-start;gap:10px;color:#FFFFFF;}
.oj-auth-story-logo-image {display:block;width:30px;height:30px;object-fit:contain;
  flex-shrink:0;filter:brightness(0) invert(1);}
.oj-auth-story-brand-name {display:block;font-size:16px;font-weight:500;line-height:1.05;}
.oj-auth-story-brand-tag {display:block;margin-top:5px;color:#C9DED3;font-size:7px;
  line-height:1;letter-spacing:.18em;white-space:nowrap;}
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
.oj-auth-brand {display:none;align-items:center;gap:.75rem;color:var(--oj-text);
  font-weight:500;line-height:1.5;margin:0 0 1rem;font-size:14px;}
.oj-auth-logo-image {display:block;width:30px;height:30px;object-fit:contain;flex-shrink:0;}
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
@keyframes oj-route-analytics {from {opacity:.78;transform:translateY(6px)}
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
  [data-testid="stDialog"]:has(.oj-chat-drawer-marker) {transition:none!important;}
  .oj-chat-loading-spinner,.oj-chat-loading-phrase,.oj-chat-stream-cursor,
  [data-testid="stDialog"]:has(.oj-chat-drawer-marker) [role="dialog"] {
    animation:none;transition:none;transform:none;}
  .oj-stage-progress-track > span {
    transition:none;}
  .oj-chat-loading-phrase {display:none;}
  .oj-chat-loading-phrase:first-child {display:block;position:static;opacity:1;}
  .st-key-auth_shell [class*="st-key-auth_stage_"],
  .st-key-workspace_shell [class*="st-key-route_content_"],.st-key-workspace_nav {
    animation:none;opacity:1;transform:none;}
  .st-key-auth_shell button,.st-key-workspace_nav button,.st-key-workspace_shell button,
  .st-key-workspace_shell [data-testid="stForm"],.oj-table tbody tr,
  .oj-analytics-table tbody tr,
  .st-key-workspace_shell [class*="st-key-catalog_problem_"] {transition:none;}
  .st-key-auth_shell button:not(:disabled):active,
  .st-key-workspace_nav button:not(:disabled):active,
  .st-key-workspace_shell button:not(:disabled):active {transform:none;}
  .st-key-workspace_shell [class*="st-key-catalog_problem_"]:hover {transform:none;}
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
  .oj-auth-brand {display:flex;}
}
@media (max-width:860px) {
  .oj-analytics-grid-two {grid-template-columns:1fr;}
  .oj-analytics-kpis {grid-template-columns:repeat(2,minmax(0,1fr));}
  .oj-admin-chart-grid {grid-template-columns:1fr;}
  .oj-admin-kpis {grid-template-columns:repeat(2,minmax(0,1fr));}
}
@media (max-width:640px) {
  .st-key-workspace_commandbar {align-items:flex-start;}
  .st-key-workspace_commandbar > [data-testid="stLayoutWrapper"]:has(
    > .st-key-workspace_header_slot) {flex:1 0 100%!important;width:100%!important;}
  .st-key-workspace_actions {width:100%;min-width:0;justify-content:flex-end;}
  [data-testid="stDialog"]:has(.oj-chat-drawer-marker) [role="dialog"] {
    position:fixed!important;inset:0!important;width:100vw!important;max-width:none!important;
    height:100dvh!important;max-height:none!important;border-radius:0!important;}
  .st-key-chat_drawer,.st-key-chat_drawer_fullscreen {padding:0 14px 12px;}
  .st-key-chat_drawer_fullscreen:has(.oj-chat-mobile-view-marker.is-history)
    .st-key-chat_fullscreen_split >
    [data-testid="stLayoutWrapper"]:has(> .st-key-chat_conversation_panel),
  .st-key-chat_drawer_fullscreen:has(.oj-chat-mobile-view-marker.is-conversation)
    .st-key-chat_fullscreen_split >
    [data-testid="stLayoutWrapper"]:has(> .st-key-chat_history_panel) {
    display:none!important;}
  .st-key-chat_fullscreen_split > [data-testid="stLayoutWrapper"] {
    width:100%!important;min-width:0!important;flex:1 1 100%!important;}
  .st-key-chat_history_panel {border-right:0;padding-right:0;}
  .st-key-chat_messages {height:calc(100dvh - 264px)!important;}
  .st-key-ai_loading_surface {padding:16px;gap:12px;}
  .st-key-workspace_shell {min-height:calc(100dvh - 6rem);}
  .oj-catalog-badges {align-items:flex-start;}
  .oj-chart,.oj-panel {padding:14px;}
  .oj-bar-meta {align-items:flex-start;}
}
@media (max-width:480px) {
  .st-key-auth_layout {margin:.5rem 0 1rem;}
  .st-key-auth_composition {border-radius:16px;}
  .st-key-auth_shell {padding:24px 20px;}
  .oj-workspace-header {gap:8px;}
  .oj-analytics-kpis {grid-template-columns:1fr;gap:8px;}
  .oj-analytics-kpi {min-height:82px;}
  .oj-admin-kpis {grid-template-columns:1fr;gap:8px;}
  .oj-command-identity {padding-right:4px;}
  .oj-command-identity > span:last-child {display:none;}
  .oj-admin-compare-row {grid-template-columns:minmax(72px,90px) minmax(90px,1fr) 52px;}
}
</style>
"""

PHRASE_KEYS = (
    "loading.phrase1",
    "loading.phrase2",
    "loading.phrase3",
    "loading.phrase4",
)


def inject():
    st.html(CSS)


def auth_story():
    st.html(
        '<section class="oj-auth-story" aria-label="'
        + html.escape(t("brand.name"), quote=True)
        + '"><div class="oj-auth-story-brand"><img class="oj-auth-story-logo-image" '
        + 'src="app/static/brand/oj-logo.png" alt=""><span><span '
        + 'class="oj-auth-story-brand-name">'
        + html.escape(t("brand.name"))
        + '</span><span class="oj-auth-story-brand-tag">OJ WORKSPACE</span></span></div>'
        + '<div><div class="oj-story-kicker">'
        + html.escape(t("story.kicker"))
        + "</div><h2>"
        + t("story.title")
        + "</h2><p>"
        + t("story.body")
        + '</p><div class="oj-story-flow"><div><span>01</span>'
        + html.escape(t("story.step1"))
        + "</div><div><span>02</span>"
        + html.escape(t("story.step2"))
        + "</div><div><span>03</span>"
        + html.escape(t("story.step3"))
        + '</div></div></div><div class="oj-story-bottom">'
        + html.escape(t("story.bottom"))
        + "</div></section>"
    )


def sidebar_brand():
    st.html(
        '<div class="oj-sidebar-brand"><img class="oj-logo-image" '
        'src="app/static/brand/oj-logo.png" alt=""><div><p class="oj-brand">编程练习室</p>'
        '<p class="oj-eyebrow">OJ WORKSPACE</p></div></div>'.replace(
            "编程练习室", html.escape(t("brand.name"))
        )
    )


def auth_brand():
    st.html(
        '<div class="oj-auth-brand"><img class="oj-auth-logo-image" '
        'src="app/static/brand/oj-logo.png" alt=""><span>'
        + html.escape(t("brand.name"))
        + "</span></div>"
    )


def active_navigation(slug):
    # Change only the selected style, never the button/container identity. This
    # keeps native keyboard focus attached while moving between route pages.
    if slug not in {"problems", "submissions", "analytics", "authoring", "account", "admin"}:
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


def workspace_header(page):
    st.html(
        '<div class="oj-workspace-header"><span>'
        + html.escape(t("nav.breadcrumb"))
        + " &nbsp;/&nbsp; <strong>"
        + html.escape(str(page))
        + "</strong></span></div>"
    )


def workspace_identity(name, role):
    safe_name = str(name).strip()
    st.html(
        '<div class="oj-command-identity"><span class="oj-command-avatar" aria-hidden="true">'
        + html.escape(safe_name[:2].upper())
        + "</span><span><strong>"
        + html.escape(safe_name)
        + "</strong><small>"
        + html.escape(str(role))
        + "</small></span></div>"
    )


def auth_identity(name):
    st.html('<p class="oj-auth-identity">' + html.escape(str(name)) + "</p>")


def loading(progress, elapsed):
    # These values are escaped before insertion. They never determine task status.
    elapsed = max(0, float(elapsed or 0))
    phrase = t(PHRASE_KEYS[int(elapsed // 10) % len(PHRASE_KEYS)])
    with st.container(key="ai_loading_surface", horizontal=True, vertical_alignment="center"):
        with st.container(key="ai_loading_mark", width=64):
            st.html(
                '<div class="oj-mark" aria-hidden="true">{<span class="oj-dot"></span>'
                '<span class="oj-dot"></span><span class="oj-dot"></span>}</div>'
            )
        with st.container(key="ai_loading_copy", gap=None):
            st.html(
                '<div class="oj-loading-title" role="status" aria-live="polite">'
                + html.escape(str(progress or t("loading.waiting")))
                + "</div>"
            )
            st.html(
                '<div class="oj-loading-note">'
                + html.escape(t("loading.elapsed", seconds=f"{elapsed:.0f}"))
                + "</div>"
            )
            st.html(
                '<div class="oj-loading-note oj-phrase" aria-hidden="true">' + phrase + "</div>"
            )
