BOT_STYLES = """
.pfb-summary { display: flex; gap: 28px; align-items: center; padding: 2px 2px 6px; }
.pfb-summary-item { display: flex; align-items: baseline; gap: 9px; }
.pfb-summary-label { color: #64748b; font-size: 12px; }
.pfb-summary-value { color: #1e293b; font-weight: 600; font-size: 15px; }
.pfb-bot-card.q-card {
  width: 100%; box-sizing: border-box; align-items: stretch; padding: 20px; gap: 0;
  border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 2px 8px #0f172a03;
  font-variant-numeric: tabular-nums;
}
.pfb-bot-header { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.pfb-bot-identity { min-width: 0; }
.pfb-bot-name { font-size: 19px; font-weight: 650; line-height: 1.3; overflow-wrap: anywhere; }
.pfb-bot-caption { font-size: 12px; color: #64748b; margin-top: 5px; }
.pfb-header-actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.pfb-state.q-badge { padding: 0; background: transparent !important; font-size: 12px; }
.pfb-state::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: currentColor; margin-right: 5px; }
.pfb-state--holding { color: #047857 !important; }
.pfb-state--waiting { color: #2563eb !important; }
.pfb-state--attention { color: #b91c1c !important; }
.pfb-state--ready, .pfb-state--paused, .pfb-state--closed { color: #64748b !important; }
.pfb-metrics { display: grid; grid-template-columns: 1.4fr .8fr 1fr; gap: 16px; margin: 18px 0; }
.pfb-metric { min-width: 0; }
.pfb-metric-label { font-size: 12px; color: #64748b; }
.pfb-metric-value { font-size: 21px; font-weight: 600; letter-spacing: -.4px; margin-top: 7px; }
.pfb-metric-value--main { font-size: 31px; font-weight: 650; line-height: 1.15; }
.pfb-value-positive { color: #059669; }
.pfb-value-negative { color: #dc2626; }
.pfb-value-neutral { color: #17243b; }
.pfb-value-unknown { color: #64748b; font-size: 18px; }
.pfb-trading-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.pfb-pnl-note { color: #64748b; font-size: 12px; }
.pfb-primary-actions { display: flex; align-items: center; gap: 7px; flex-shrink: 0; }
.pfb-action.q-btn { min-height: 34px; padding: 4px 11px; font-size: 12px; box-shadow: none; border-radius: 6px; color: #475569 !important; }
.pfb-action .q-icon, .pfb-secondary-button .q-icon { font-size: 16px; }
.pfb-run.q-btn { background: #059669 !important; color: white !important; }
.pfb-close.q-btn { color: #b45309 !important; }
.pfb-secondary-button.q-btn { color: #64748b !important; font-size: 12px; padding: 4px 6px; border-radius: 6px; }
.pfb-notice { display: flex; align-items: flex-start; gap: 8px; padding: 12px; margin: 16px 0 0;
  background: #fef2f2; color: #b91c1c; border: 1px solid #fee2e2; border-radius: 7px; font-size: 13px; }
.pfb-data-warning { padding: 7px 12px; background: #fffbeb; color: #92400e; border-radius: 7px; font-size: 12px; margin-top: 12px; }
.pfb-position-heading { display: flex; align-items: center; justify-content: space-between; margin: 20px 0 9px; }
.pfb-section-title { color: #475569; font-size: 12px; font-weight: 500; }
.pfb-match.q-badge { background: transparent !important; padding: 0; font-size: 12px; }
.pfb-match--good { color: #047857 !important; }
.pfb-match--unknown { color: #64748b !important; }
.pfb-match--bad { color: #dc2626 !important; }
.pfb-leg-table { border: 1px solid #e5eaf0; border-radius: 8px; overflow: hidden; }
.pfb-leg-table-head, .pfb-leg { display: grid; grid-template-columns: 1.15fr 1.1fr 1fr 1.2fr; gap: 12px; padding: 11px 14px; }
.pfb-leg-table-head { background: #f8fafc; color: #64748b; font-size: 11px; }
.pfb-leg { border-top: 1px solid #edf1f5; align-items: center; padding-top: 14px; padding-bottom: 14px; }
.pfb-leg-head { display: flex; align-items: center; gap: 6px; min-width: 0; }
.pfb-leg-role { font-size: 11px; font-weight: 500; flex-shrink: 0; }
.pfb-leg-role--long { color: #047857; }
.pfb-leg-role--short { color: #b91c1c; }
.pfb-leg-account { font-size: 13px; font-weight: 500; overflow-wrap: anywhere; }
.pfb-leg-provider { color: #64748b; font-size: 11px; margin-top: 3px; }
.pfb-leg-quantity { font-size: 13px; font-weight: 500; white-space: nowrap; }
.pfb-leg-quantity--empty { font-size: 12px; color: #64748b; white-space: normal; }
.pfb-leg-entry { font-size: 13px; }
.pfb-leg-rate { font-size: 12px; }
.pfb-leg-label { color: #64748b; font-size: 11px; margin-top: 2px; }
.pfb-mobile-label { display: none; }
.pfb-funding-summary { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 12px 1px 0; }
.pfb-funding-summary .pfb-leg-label { font-size: 12px; }
.pfb-funding-value { color: #475569; font-size: 12px; text-align: right; }
.pfb-card-links { display: flex; justify-content: flex-end; gap: 3px; }
.pfb-trading-toolbar { margin-top: 16px; padding-top: 14px; border-top: 1px solid #edf1f5; flex-wrap: wrap; }
.pfb-parameters { color: #64748b; font-size: 11px; margin-top: 10px; }
.pfb-delete-button.q-btn { font-size: 12px; padding: 4px 6px; color: #b45353 !important; border-radius: 6px; }
.pfb-delete-button .q-icon { font-size: 16px; }
.pfb-wall-toolbar { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; }
.pfb-wall-toggle { font-size: 11px; color: #64748b; }
.pfb-grid-inventory { margin-top: 0; }
.pfb-strategy-monitor { margin-top: 0; padding: 14px; border: 1px solid #e2e8f0;
  border-radius: 10px; background: linear-gradient(130deg, #f8fafc 0%, #fff 70%); }
.pfb-monitor-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.pfb-monitor-title { font-size: 14px; font-weight: 650; color: #17243b; }
.pfb-monitor-health { font-size: 11px; color: #64748b; }
.pfb-monitor-health--live { color: #047857; }
.pfb-monitor-health--live::before { content: ''; display: inline-block; width: 5px; height: 5px;
  border-radius: 50%; background: #10b981; margin-right: 5px; vertical-align: middle; }
.pfb-monitor-caption { margin-top: 4px; color: #64748b; font-size: 11px; }
.pfb-monitor-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 12px; }
.pfb-monitor-stat-title { font-size: 11px; color: #64748b; }
.pfb-monitor-stat-value { margin-top: 5px; font-size: 22px; font-weight: 650; color: #1e293b; letter-spacing: -.4px; }
.pfb-monitor-stat-hint { margin-top: 4px; font-size: 11px; color: #64748b; }
.pfb-grid-monitor .pfb-monitor-stat:nth-child(2) .pfb-monitor-stat-value { color: #047857; }
.pfb-grid-monitor .pfb-monitor-stat:nth-child(3) .pfb-monitor-stat-value { color: #be3851; }
.pfb-monitor-status { font-size: 13px; font-weight: 600; color: #334155; margin-top: 12px; }
.pfb-monitor-explanation { color: #64748b; font-size: 12px; line-height: 1.7; margin-top: 3px; }
.pfb-grid-inventory { margin-top: 13px; color: #475569; font-size: 11px; }
.pfb-grid-wall { margin-top: 12px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #fff; }
.pfb-grid-wall-head, .pfb-grid-line { display: grid; grid-template-columns: 1.1fr 1fr 1.1fr 1.2fr;
  align-items: center; gap: 10px; padding: 7px 12px; }
.pfb-grid-wall-head { color: #64748b; font-size: 10px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }
.pfb-grid-wall-head > :last-child, .pfb-grid-line-status { text-align: right; }
.pfb-grid-lines { display: flex; flex-direction: column; max-height: 320px; overflow-y: auto; }
.pfb-grid-line { font-size: 12px; border-bottom: 1px solid #edf1f5; min-height: 32px; }
.pfb-grid-line.hidden { display: none !important; }
.pfb-grid-line--sell { background: #fffafb; }
.pfb-grid-line--buy { background: #f9fdfb; }
.pfb-grid-line--sell .pfb-grid-line-price, .pfb-grid-line--sell .pfb-grid-line-action { color: #be3851; }
.pfb-grid-line--buy .pfb-grid-line-price, .pfb-grid-line--buy .pfb-grid-line-action { color: #047857; }
.pfb-grid-line--sell.pfb-grid-line--next { background: #fff0f3; box-shadow: inset 3px 0 #e85c75; }
.pfb-grid-line--buy.pfb-grid-line--next { background: #eaf8f2; box-shadow: inset 3px 0 #10a675; }
.pfb-grid-line-price { font-weight: 600; }
.pfb-grid-line-quantity { color: #475569; font-size: 11px; }
.pfb-grid-line-status { color: #94a3b8; font-size: 10px; }
.pfb-grid-line--next .pfb-grid-line-status { color: #475569; font-weight: 600; }
.pfb-grid-line--cursor { color: #94a3b8; background: #f8fafc; }
.pfb-grid-line--cursor .pfb-grid-line-price { color: #64748b; }
.pfb-grid-ticker { display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  color: #1d4ed8; background: #edf4ff; border-top: 1px solid #dbeafe; border-bottom: 1px solid #dbeafe;
  font-size: 12px; font-weight: 600; }
.pfb-grid-ticker-hint { font-size: 10px; font-weight: 400; margin-left: auto; color: #64748b; }
.pfb-monitor-empty { color: #64748b; font-size: 12px; padding: 15px 0; }
.pfb-monitor-footnote { color: #94a3b8; font-size: 10px; line-height: 1.6; margin-top: 9px; }
@media (max-width: 520px) {
  .pfb-bot-card.q-card { padding: 16px; }
  .pfb-metrics { grid-template-columns: 1.3fr .8fr 1fr; gap: 10px; margin: 16px 0; }
  .pfb-metric-value { font-size: 18px; }
  .pfb-metric-value--main { font-size: 26px; }
  .pfb-metric-value--main.pfb-value-unknown { font-size: 17px; }
  .pfb-trading-toolbar { flex-wrap: wrap; }
  .pfb-primary-actions { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .pfb-leg-table-head { display: none; }
  .pfb-leg { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
  .pfb-leg-quantity { text-align: right; }
  .pfb-leg-funding { text-align: right; }
  .pfb-mobile-label { display: block; color: #64748b; font-size: 11px; margin-bottom: 2px; }
  .pfb-bot-name { font-size: 17px; }
  .pfb-header-actions { gap: 3px; }
  .pfb-strategy-monitor { padding: 13px; }
  .pfb-monitor-stats { gap: 10px; }
  .pfb-monitor-stat-value { font-size: 18px; }
  .pfb-monitor-stat-hint { font-size: 10px; }
  .pfb-grid-wall-head, .pfb-grid-line { grid-template-columns: 1fr .8fr 1fr; gap: 7px; padding: 9px; }
  .pfb-grid-wall-head > :last-child { display: none; }
  .pfb-grid-line-status { grid-column: 1 / -1; text-align: left; font-size: 10px; margin-top: -4px; }
  .pfb-grid-line { min-height: 50px; }
}
"""
