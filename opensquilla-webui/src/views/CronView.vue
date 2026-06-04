<template>
  <div class="cron-stage">
    <header class="cron-stage__header">
      <div class="cron-stage__title-block">
        <span class="cron-stage__eyebrow">Control &middot; Schedule</span>
        <h2 class="cron-stage__title">Cron Jobs</h2>
        <p class="cron-stage__subtitle">Time-driven tasks &mdash; orchestrate reminders, agent turns, and recurring work.</p>
      </div>
      <div class="cron-stage__actions">
        <div class="cron-search-wrap">
          <span class="cron-search-icon"><Icon name="search" :size="16" /></span>
          <input
            v-model="searchText"
            class="cron-search-input"
            type="search"
            placeholder="Search jobs&hellip;"
            autocomplete="off"
          >
        </div>
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" /><span>Refresh</span>
        </button>
        <button class="btn btn--primary" @click="openPanel(null)">
          <Icon name="plus" :size="16" /><span>New job</span>
        </button>
      </div>
    </header>

    <!-- Summary -->
    <section class="cron-summary">
      <div class="stat stat--hero">
        <div class="stat-label">Active schedules</div>
        <div class="stat-value">{{ enabledCount }}<span class="stat-total"> / {{ jobs.length }}</span></div>
        <div class="stat-hint">{{ pausedCount ? `${pausedCount} paused` : 'all enabled' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Next run</div>
        <div class="stat-value mono">{{ nextCountdown }}</div>
        <div class="stat-hint">{{ nextRunHint }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Last 24h runs</div>
        <div class="stat-value">{{ last24h.runs }}</div>
        <div class="stat-hint">
          <span v-if="last24h.ok" class="cron-pos">{{ last24h.ok }} ok</span>
          <span v-if="last24h.ok && last24h.err"> &middot; </span>
          <span v-if="last24h.err" class="cron-neg">{{ last24h.err }} fail</span>
          <span v-if="!last24h.ok && !last24h.err">awaiting first run</span>
        </div>
      </div>
      <div class="stat">
        <div class="stat-label">Mix</div>
        <div class="stat-value">
          <span title="Reminders"><span class="stat__chip stat__chip--info">{{ reminderCount }}</span></span>
          <span>/</span>
          <span title="Agent tasks"><span class="stat__chip stat__chip--accent">{{ agentTaskCount }}</span></span>
        </div>
        <div class="stat-hint">reminders &middot; agent tasks</div>
      </div>
    </section>

    <!-- Horizon -->
    <section v-if="upcomingHorizon.length > 0" class="cron-horizon">
      <div class="cron-horizon__head">
        <span class="cron-horizon__title">Next 12 hours</span>
        <span class="cron-horizon__legend"><span class="cron-horizon__dot" />upcoming run</span>
      </div>
      <div class="cron-horizon__rail">
        <button
          v-for="(o, i) in upcomingHorizon"
          :key="o.job.id"
          class="cron-horizon__marker"
          :style="{ left: horizonLeft(o.ts), '--i': i }"
          @click="onHorizonClick(o.job.id)"
        >
          <span class="cron-horizon__marker-dot" />
          <span class="cron-horizon__marker-tip">
            <strong>{{ o.job.name || o.job.id }}</strong>
            <em>{{ humanCountdown(new Date(o.ts)) }}</em>
          </span>
        </button>
      </div>
      <div class="cron-horizon__axis">
        <span
          v-for="h in [0, 3, 6, 9, 12]"
          :key="h"
          class="cron-horizon__tick"
          :style="{ left: (h / 12) * 100 + '%' }"
        >
          <span class="cron-horizon__tick-line" />
          <span class="cron-horizon__tick-label">{{ h === 0 ? 'now' : horizonTickLabel(h) }}</span>
        </span>
      </div>
    </section>

    <!-- Jobs list -->
    <section class="cron-jobs">
      <div class="cron-jobs__head">
        <h3 class="cron-jobs__title">
          <template v-if="searchText">Matching schedules <span class="cron-jobs__count">{{ filteredSortedJobs.length }} of {{ jobs.length }}</span></template>
          <template v-else>All schedules <span class="cron-jobs__count">{{ filteredSortedJobs.length }}</span></template>
        </h3>
        <div class="cron-view-toggle" role="tablist" aria-label="View mode">
          <button
            class="cron-view-toggle__btn"
            :class="{ 'is-active': viewMode === 'cards' }"
            role="tab"
            @click="viewMode = 'cards'"
          >Cards</button>
          <button
            class="cron-view-toggle__btn"
            :class="{ 'is-active': viewMode === 'table' }"
            role="tab"
            @click="viewMode = 'table'"
          >Table</button>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="filteredSortedJobs.length === 0" class="state">
        <template v-if="jobs.length === 0">
          <div class="cron-empty__clock" aria-hidden="true">
            <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <radialGradient id="cg" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stop-color="rgba(240,160,48,0.20)" />
                  <stop offset="60%" stop-color="rgba(240,160,48,0.05)" />
                  <stop offset="100%" stop-color="rgba(240,160,48,0)" />
                </radialGradient>
              </defs>
              <circle cx="60" cy="60" r="58" fill="url(#cg)" />
              <circle cx="60" cy="60" r="44" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1" />
              <circle cx="60" cy="60" r="44" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="2 6" class="cron-empty__ring" />
              <line
                v-for="deg in [0,30,60,90,120,150,180,210,240,270,300,330]"
                :key="deg"
                :x1="60 + Math.cos(deg * Math.PI / 180) * 40"
                :y1="60 + Math.sin(deg * Math.PI / 180) * 40"
                :x2="60 + Math.cos(deg * Math.PI / 180) * (deg % 90 === 0 ? 32 : 36)"
                :y2="60 + Math.sin(deg * Math.PI / 180) * (deg % 90 === 0 ? 32 : 36)"
                stroke="currentColor"
                :stroke-opacity="deg % 90 === 0 ? 0.5 : 0.25"
                :stroke-width="deg % 90 === 0 ? 1.5 : 1"
              />
              <line x1="60" y1="60" x2="60" y2="28" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" class="cron-empty__hand" />
              <line x1="60" y1="60" x2="84" y2="60" stroke="currentColor" stroke-opacity="0.6" stroke-width="2" stroke-linecap="round" />
              <circle cx="60" cy="60" r="3" fill="var(--accent)" />
            </svg>
          </div>
          <div class="cron-empty__title">Set the rhythm.</div>
          <p class="cron-empty__msg">No schedules yet. Create your first cron job to wake an agent, fire a reminder,<br>or kick off recurring work &mdash; all on time, all on your terms.</p>
          <button class="btn btn--primary cron-empty__cta" @click="openPanel(null)">
            <Icon name="plus" :size="16" /><span>Create your first schedule</span>
          </button>
          <div class="cron-empty__hints">
            <span class="cron-empty__hints-label">Try a preset</span>
            <button
              class="cron-empty-hint"
              @click="openPanel(null, { name: 'Daily standup nudge', expression: '0 9 * * 1-5', payloadKind: 'reminder', message: 'Good morning! Time for standup.' })"
            >
              <code>0 9 * * 1-5</code>
              <span>Weekday morning reminder</span>
            </button>
            <button
              class="cron-empty-hint"
              @click="openPanel(null, { name: 'Hourly health check', expression: '0 * * * *', payloadKind: 'agent_turn', message: 'Run a quick system health check and report any anomalies.' })"
            >
              <code>0 * * * *</code>
              <span>Hourly agent check</span>
            </button>
            <button
              class="cron-empty-hint"
              @click="openPanel(null, { name: 'Friday wrap-up', expression: '0 17 * * 5', payloadKind: 'agent_turn', message: 'Summarize this week\'s work and propose next week\'s priorities.' })"
            >
              <code>0 17 * * 5</code>
              <span>Friday agent wrap-up</span>
            </button>
          </div>
        </template>
        <template v-else>
          <div class="state-icon"><Icon name="search" :size="48" /></div>
          <div class="state-title">No matches</div>
          <p class="state-text">No schedules match your search. Try a different query, or clear it to see everything.</p>
        </template>
      </div>

      <!-- Cards view -->
      <div v-else-if="viewMode === 'cards'" class="cron-card-grid">
        <article
          v-for="(j, i) in filteredSortedJobs"
          :key="j.id"
          class="cron-card"
          :class="{ 'is-selected': selectedId === j.id, 'is-imminent': isImminent(j) }"
          :style="{ '--stagger': i }"
          :data-cron-row="j.id"
        >
          <header class="cron-card__head">
            <span class="cron-card__dot" :class="dotClass(j)" />
            <button type="button" class="cron-card__name" title="Show run history" @click="toggleSelected(j.id)">
              {{ j.name || j.id }}
            </button>
            <span class="cron-pill" :class="`cron-pill--${jobKindClass(j)}`">{{ jobKindLabel(j) }}</span>
          </header>
          <div class="cron-card__schedule">
            <code class="cron-expr">{{ j.expression || j.schedule || '—' }}</code>
            <span v-if="explainCron(j.expression || '')" class="cron-card__human">{{ explainCron(j.expression || '') }}</span>
          </div>
          <dl class="cron-card__meta">
            <div><dt>Target</dt><dd>{{ j.sessionTarget || j.session_target || '—' }}</dd></div>
            <div>
              <dt>Last run</dt>
              <dd>
                {{ j.last_run ? humanCountdownPast(new Date(j.last_run)) : '—' }}
                <span v-if="j.last_status">
                  &middot; <span :class="`status status--${j.last_status === 'ok' || j.last_status === 'success' ? 'ok' : 'err'}`">{{ j.last_status }}</span>
                </span>
              </dd>
            </div>
            <div>
              <dt>Next run</dt>
              <dd>
                <template v-if="j.enabled">
                  <span class="cron-mono">{{ nextRunText(j) }}</span>
                  <span v-if="nextRunAbs(j)" class="cron-card__abs"> &middot; {{ nextRunAbs(j) }}</span>
                </template>
                <span v-else class="cron-muted">paused</span>
              </dd>
            </div>
            <div v-if="(j.message || j.prompt || '').trim()" class="cron-card__message">
              <dt>Prompt</dt>
              <dd>{{ ((j.message || j.prompt || '').trim().length > 140 ? (j.message || j.prompt || '').trim().slice(0, 140) + '&hellip;' : (j.message || j.prompt || '').trim()) }}</dd>
            </div>
          </dl>
          <footer class="cron-card__actions">
            <button
              class="cron-iconbtn cron-iconbtn--accent"
              title="Run now"
              :disabled="isJobRunning(j.id)"
              @click="runJob(j.id)"
            >
              <span v-if="isJobRunning(j.id)" class="cron-spinner" aria-hidden="true"></span>
              <Icon v-else name="send" :size="16" />
              <span>{{ isJobRunning(j.id) ? 'Running...' : 'Run' }}</span>
            </button>
            <button class="cron-iconbtn" :title="j.enabled ? 'Pause' : 'Resume'" @click="toggleJob(j)">
              <Icon :name="j.enabled ? 'stop' : 'send'" :size="16" /><span>{{ j.enabled ? 'Pause' : 'Resume' }}</span>
            </button>
            <button class="cron-iconbtn" title="Edit" @click="openPanel(j)">
              <Icon name="edit" :size="16" /><span>Edit</span>
            </button>
            <button class="cron-iconbtn cron-iconbtn--danger" title="Delete" @click="deleteJob(j)">
              <Icon name="trash" :size="16" />
            </button>
          </footer>
        </article>
      </div>

      <!-- Table view -->
      <div v-else class="cron-table-wrap">
        <table class="cron-table">
          <thead>
            <tr>
              <th v-for="col in tableCols" :key="col.key" :class="{ 'cron-th-sort': sortableCols.includes(col.key) }" @click="sortableCols.includes(col.key) ? onSort(col.key) : undefined">
                {{ col.label }}
                <span v-if="sortCol === col.key" class="cron-table__arrow">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="j in filteredSortedJobs"
              :key="j.id"
              :class="{ 'is-selected': selectedId === j.id, 'is-imminent': isImminent(j) }"
              :data-cron-row="j.id"
            >
              <td>
                <span class="cron-card__dot" :class="dotClass(j)" />
                <button class="cron-link" @click="toggleSelected(j.id)">{{ j.name || j.id }}</button>
              </td>
              <td><span class="cron-pill" :class="`cron-pill--${jobKindClass(j)}`">{{ jobKindLabel(j) }}</span></td>
              <td>{{ j.sessionTarget || j.session_target || '—' }}</td>
              <td><code class="cron-expr cron-expr--inline">{{ j.expression || j.schedule || '—' }}</code></td>
              <td>
                <span v-if="j.enabled" class="status status--ok">enabled</span>
                <span v-else class="status status--off">paused</span>
              </td>
              <td class="cron-mono">{{ j.last_run ? humanCountdownPast(new Date(j.last_run)) : '—' }}</td>
              <td class="cron-mono">{{ j.enabled ? nextRunText(j) : '—' }}</td>
              <td class="cron-table__actions">
                <button
                  class="cron-iconbtn cron-iconbtn--sm"
                  :title="isJobRunning(j.id) ? 'Running' : 'Run now'"
                  :disabled="isJobRunning(j.id)"
                  @click="runJob(j.id)"
                >
                  <span v-if="isJobRunning(j.id)" class="cron-spinner" aria-hidden="true"></span>
                  <Icon v-else name="send" :size="14" />
                </button>
                <button class="cron-iconbtn cron-iconbtn--sm" :title="j.enabled ? 'Pause' : 'Resume'" @click="toggleJob(j)">
                  <Icon :name="j.enabled ? 'stop' : 'send'" :size="14" />
                </button>
                <button class="cron-iconbtn cron-iconbtn--sm" title="Edit" @click="openPanel(j)">
                  <Icon name="edit" :size="14" />
                </button>
                <button class="cron-iconbtn cron-iconbtn--sm cron-iconbtn--danger" title="Delete" @click="deleteJob(j)">
                  <Icon name="trash" :size="14" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Detail panel (run history) -->
      <CronRunHistory
        v-if="selectedId && selectedJob"
        :job="selectedJob"
        :runs="runs"
        :loading="runsLoading"
        @close="selectedId = null"
        @open-chat="openRunChat"
      />
    </section>

    <!-- Slide-in edit/add panel -->
    <Teleport to="body">
      <Transition name="panel">
        <div v-if="panelOpen" class="cron-panel-overlay">
          <div class="cron-panel__scrim" :class="{ 'is-open': panelOpen }" @click="closePanel" />
          <div class="cron-panel" :class="{ 'is-open': panelOpen }">
            <div class="cron-panel__head">
              <div>
                <span class="cron-panel__eyebrow">{{ editingJob ? 'Edit schedule' : 'New schedule' }}</span>
                <h3 class="cron-panel__title">{{ editingJob ? 'Edit Schedule' : 'Create a job' }}</h3>
              </div>
              <button class="cron-iconbtn" aria-label="Close" @click="closePanel">
                <Icon name="x" :size="16" />
              </button>
            </div>
            <div class="cron-panel__body">
              <div class="cron-field">
                <label class="cron-field__label" for="cp-name">Name</label>
                <input id="cp-name" v-model="formName" class="cron-field__input" type="text" placeholder="my-job" autocomplete="off">
              </div>

              <div class="cron-field">
                <label class="cron-field__label" for="cp-type">Schedule type</label>
                <select id="cp-type" v-model="formType" class="cron-field__input">
                  <option value="cron">Cron expression</option>
                  <option value="every">Fixed interval</option>
                  <option value="at">One-time ISO time</option>
                </select>
              </div>

              <div v-show="formType === 'cron'" class="cron-field">
                <label class="cron-field__label" for="cp-cron">Cron expression</label>
                <input
                  id="cp-cron"
                  v-model="formCron"
                  class="cron-field__input cron-field__input--mono"
                  type="text"
                  placeholder="0 9 * * 1-5"
                  autocomplete="off"
                  spellcheck="false"
                  @input="onCronInput"
                >
                <div class="cron-explain" :class="{ 'is-valid': cronExplainValid, 'is-invalid': cronExplainInvalid }">
                  <div class="cron-explain__human">{{ cronExplainHuman }}</div>
                  <div v-if="!cronExplainValid && !cronExplainInvalid" class="cron-explain__hint">
                    e.g. <code>*/15 * * * *</code>, <code>0 9 * * 1-5</code>, <code>0 0 1 * *</code>
                  </div>
                  <ul v-if="cronExplainUpcoming.length > 0" class="cron-explain__upcoming">
                    <li v-for="(d, i) in cronExplainUpcoming" :key="i">
                      <span class="cron-explain__num">{{ i + 1 }}.</span>
                      <span class="cron-mono">{{ humanCountdown(d) }}</span>
                      <span class="cron-explain__abs">{{ humanTime(d) }}</span>
                    </li>
                  </ul>
                </div>
                <div class="cron-presets">
                  <span class="cron-presets__label">Presets:</span>
                  <button type="button" class="cron-preset" @click="applyPreset('*/5 * * * *')">Every 5m</button>
                  <button type="button" class="cron-preset" @click="applyPreset('0 * * * *')">Hourly</button>
                  <button type="button" class="cron-preset" @click="applyPreset('0 9 * * 1-5')">Weekdays 09:00</button>
                  <button type="button" class="cron-preset" @click="applyPreset('0 0 * * 0')">Sundays midnight</button>
                </div>
              </div>

              <div v-show="formType === 'every'" class="cron-field">
                <label class="cron-field__label" for="cp-every">Interval (seconds)</label>
                <input id="cp-every" v-model="formEvery" class="cron-field__input" type="number" min="1" placeholder="60">
              </div>

              <div v-show="formType === 'at'" class="cron-field">
                <label class="cron-field__label" for="cp-at">ISO time</label>
                <input id="cp-at" v-model="formAt" class="cron-field__input cron-field__input--mono" type="text" placeholder="2026-05-18T09:00:00+08:00">
              </div>

              <div class="cron-field">
                <label class="cron-field__label" for="cp-tz">Timezone (IANA)</label>
                <input id="cp-tz" v-model="formTz" class="cron-field__input cron-field__input--mono" type="text" placeholder="America/Los_Angeles" autocomplete="off" spellcheck="false">
                <div class="cron-field__hint">Leave empty to evaluate the cron expression in UTC. Example: <code>Asia/Shanghai</code>, <code>Europe/London</code>.</div>
              </div>

              <div class="cron-field">
                <label class="cron-field__label" for="cp-payload-kind">Job mode</label>
                <select id="cp-payload-kind" v-model="formPayloadKind" class="cron-field__input" @change="onPayloadKindChange">
                  <option value="reminder">Static Reminder (no model)</option>
                  <option value="agent_turn">Background Agent Task (choose session)</option>
                  <option value="system_event">System Event (Main)</option>
                </select>
                <div class="cron-field__hint">{{ jobModeHint }}</div>
              </div>

              <div class="cron-field">
                <label class="cron-field__label" for="cp-agent-id">Agent ID</label>
                <input id="cp-agent-id" v-model="formAgentId" class="cron-field__input" type="text" placeholder="main">
              </div>

              <div v-show="formPayloadKind === 'agent_turn'" class="cron-field">
                <label class="cron-field__label" for="cp-session-target">Session target</label>
                <select id="cp-session-target" v-model="formSessionTarget" class="cron-field__input" @change="onSessionTargetChange">
                  <option value="main">Agent main session</option>
                  <option value="current">Current chat session</option>
                  <option value="isolated">Isolated cron session</option>
                  <option value="session">Named session</option>
                </select>
                <div class="cron-field__hint">{{ sessionTargetHint }}</div>
              </div>

              <div v-show="showTargetSessionRow" class="cron-field">
                <label class="cron-field__label" for="cp-target-session-key">{{ targetSessionLabel }}</label>
                <input id="cp-target-session-key" v-model="formTargetSessionKey" class="cron-field__input" type="text" placeholder="agent:main:webchat:abc123">
                <div class="cron-field__hint">{{ targetSessionHint }}</div>
              </div>

              <div class="cron-field">
                <label class="cron-field__label" for="cp-message">{{ messageLabel }}</label>
                <textarea id="cp-message" v-model="formMessage" class="cron-field__input cron-field__input--textarea" rows="4" placeholder="Run daily report&hellip;" />
              </div>

              <details class="cron-advanced">
                <summary class="cron-advanced__summary">Advanced delivery &amp; wake</summary>
                <div class="cron-advanced__body">
                  <div class="cron-field">
                    <label class="cron-field__label" for="cp-wake-mode">Wake mode</label>
                    <select id="cp-wake-mode" v-model="formWakeMode" class="cron-field__input">
                      <option value="now">Now (fire immediately on schedule)</option>
                      <option value="next-heartbeat">Next heartbeat (defer to main loop)</option>
                    </select>
                    <div class="cron-field__hint">Use <code>next-heartbeat</code> for main-session jobs that should ride the existing turn queue.</div>
                  </div>

                  <div class="cron-field">
                    <label class="cron-field__label" for="cp-delivery-mode">Delivery mode</label>
                    <select id="cp-delivery-mode" v-model="formDeliveryMode" class="cron-field__input" @change="onDeliveryModeChange">
                      <option value="">Default (inferred from session)</option>
                      <option value="none">None (run silently)</option>
                      <option value="announce">Announce to channel</option>
                      <option value="webhook">Post to webhook</option>
                    </select>
                  </div>

                  <div v-show="formDeliveryMode === 'announce'" class="cron-field">
                    <label class="cron-field__label" for="cp-delivery-channel">Channel</label>
                    <input id="cp-delivery-channel" v-model="formDeliveryChannel" class="cron-field__input" type="text" placeholder="slack" autocomplete="off">
                  </div>
                  <div v-show="formDeliveryMode === 'announce'" class="cron-field">
                    <label class="cron-field__label" for="cp-delivery-to">Recipient</label>
                    <input id="cp-delivery-to" v-model="formDeliveryTo" class="cron-field__input" type="text" placeholder="C-team-alerts" autocomplete="off">
                  </div>
                  <div v-show="formDeliveryMode === 'announce'" class="cron-field">
                    <label class="cron-field__label" for="cp-delivery-account">Account id</label>
                    <input id="cp-delivery-account" v-model="formDeliveryAccount" class="cron-field__input" type="text" placeholder="" autocomplete="off">
                  </div>

                  <div v-show="formDeliveryMode === 'webhook'" class="cron-field">
                    <label class="cron-field__label" for="cp-delivery-webhook-url">Webhook URL</label>
                    <input id="cp-delivery-webhook-url" v-model="formDeliveryWebhookUrl" class="cron-field__input cron-field__input--mono" type="url" placeholder="https://hooks.example/cron" autocomplete="off">
                  </div>
                  <div v-show="formDeliveryMode === 'webhook'" class="cron-field">
                    <label class="cron-field__label" for="cp-delivery-webhook-token">Webhook bearer token</label>
                    <input id="cp-delivery-webhook-token" v-model="formDeliveryWebhookToken" class="cron-field__input" type="password" placeholder="optional bearer token" autocomplete="off">
                  </div>

                  <label v-show="formDeliveryMode === 'announce' || formDeliveryMode === 'webhook'" class="cron-toggle">
                    <input v-model="formDeliveryBestEffort" type="checkbox">
                    <span class="cron-toggle__track"><span class="cron-toggle__thumb" /></span>
                    <span class="cron-toggle__label">Best-effort delivery (do not fail the job when delivery fails)</span>
                  </label>

                  <details class="cron-advanced cron-advanced--nested">
                    <summary class="cron-advanced__summary">Failure destination</summary>
                    <div class="cron-advanced__body">
                      <div class="cron-field">
                        <label class="cron-field__label" for="cp-fd-mode">Route failures to</label>
                        <select id="cp-fd-mode" v-model="formFdMode" class="cron-field__input" @change="onFdModeChange">
                          <option value="">Disabled (no separate failure alert)</option>
                          <option value="channel">A channel</option>
                          <option value="webhook">A webhook</option>
                        </select>
                      </div>
                      <div v-show="formFdMode === 'channel'" class="cron-field">
                        <label class="cron-field__label" for="cp-fd-channel">Channel</label>
                        <input id="cp-fd-channel" v-model="formFdChannel" class="cron-field__input" type="text" placeholder="slack" autocomplete="off">
                      </div>
                      <div v-show="formFdMode === 'channel'" class="cron-field">
                        <label class="cron-field__label" for="cp-fd-to">Recipient</label>
                        <input id="cp-fd-to" v-model="formFdTo" class="cron-field__input" type="text" placeholder="C-ops-alerts" autocomplete="off">
                      </div>
                      <div v-show="formFdMode === 'channel'" class="cron-field">
                        <label class="cron-field__label" for="cp-fd-account">Account id</label>
                        <input id="cp-fd-account" v-model="formFdAccount" class="cron-field__input" type="text" placeholder="" autocomplete="off">
                      </div>
                      <div v-show="formFdMode === 'webhook'" class="cron-field">
                        <label class="cron-field__label" for="cp-fd-webhook-url">Webhook URL</label>
                        <input id="cp-fd-webhook-url" v-model="formFdWebhookUrl" class="cron-field__input cron-field__input--mono" type="url" placeholder="https://hooks.example/alert" autocomplete="off">
                      </div>
                      <div v-show="formFdMode === 'webhook'" class="cron-field">
                        <label class="cron-field__label" for="cp-fd-webhook-token">Webhook bearer token</label>
                        <input id="cp-fd-webhook-token" v-model="formFdWebhookToken" class="cron-field__input" type="password" placeholder="optional bearer token" autocomplete="off">
                      </div>
                    </div>
                  </details>
                </div>
              </details>

              <label class="cron-toggle">
                <input v-model="formEnabled" type="checkbox">
                <span class="cron-toggle__track"><span class="cron-toggle__thumb" /></span>
                <span class="cron-toggle__label">Enabled</span>
              </label>

              <div class="cron-panel__actions">
                <button class="btn btn--primary" @click="saveJob">Save schedule</button>
                <button class="btn btn--ghost" @click="closePanel">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Delete confirm modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="deleteModalOpen" class="modal-overlay" @click="deleteModalOpen = false">
          <div class="modal" @click.stop>
            <h3 class="modal__title">Delete schedule</h3>
            <div class="modal__body">
              <p>Delete <strong>{{ deleteTarget?.name || deleteTarget?.id }}</strong>? This cannot be undone.</p>
            </div>
            <div class="modal__footer">
              <button class="btn btn--danger" @click="confirmDelete">Delete</button>
              <button class="btn btn--ghost" @click="deleteModalOpen = false">Cancel</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import CronRunHistory from '@/components/cron/CronRunHistory.vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CronJob {
  id: string
  name?: string
  enabled?: boolean
  status?: string
  next_run?: string
  last_run?: string
  last_status?: string
  expression?: string
  schedule?: string
  payloadKind?: string
  payload_kind?: string
  message?: string
  prompt?: string
  sessionTarget?: string
  session_target?: string
  scheduleKind?: string
  schedule_kind?: string
  scheduleRaw?: string
  schedule_raw?: string
  tz?: string
  wakeMode?: string
  wake_mode?: string
  agentId?: string
  delivery?: DeliveryConfig
  originSessionKey?: string
  origin_session_key?: string
  targetSessionKey?: string
  target_session_key?: string
  sessionKey?: string
  session_key?: string
}

interface DeliveryConfig {
  mode?: string
  channelName?: string
  to?: string
  channelId?: string
  accountId?: string
  webhookUrl?: string
  webhookToken?: string
  bestEffort?: boolean
  failureDestination?: FailureDestination
}

interface FailureDestination {
  mode?: string
  channelName?: string
  to?: string
  channelId?: string
  accountId?: string
  webhookUrl?: string
  webhookToken?: string
}

interface CronRun {
  started_at?: string
  status?: string
  duration_ms?: number
  deliveryStatus?: Record<string, unknown> | string
  delivery_status?: Record<string, unknown> | string
  summary?: string
  sessionKey?: string
}

interface PanelTemplate {
  name?: string
  expression?: string
  payloadKind?: string
  message?: string
  scheduleKind?: string
  schedule_kind?: string
  every_seconds?: number
  at?: string
  tz?: string
  wakeMode?: string
  sessionTarget?: string
  agentId?: string
  targetSessionKey?: string
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const route = useRoute()
const router = useRouter()

const jobs = ref<CronJob[]>([])
const selectedId = ref<string | null>(null)
const searchText = ref('')
const viewMode = ref<'cards' | 'table'>('cards')
const runningJobIds = ref<Set<string>>(new Set())

const panelOpen = ref(false)
const editingJob = ref<CronJob | null>(null)

// Form fields
const formName = ref('')
const formType = ref('cron')
const formCron = ref('')
const formEvery = ref('')
const formAt = ref('')
const formTz = ref('')
const formPayloadKind = ref('reminder')
const formAgentId = ref('main')
const formSessionTarget = ref('isolated')
const formTargetSessionKey = ref('')
const formMessage = ref('')
const formWakeMode = ref('now')
const formDeliveryMode = ref('')
const formDeliveryChannel = ref('')
const formDeliveryTo = ref('')
const formDeliveryAccount = ref('')
const formDeliveryWebhookUrl = ref('')
const formDeliveryWebhookToken = ref('')
const formDeliveryBestEffort = ref(false)
const formFdMode = ref('')
const formFdChannel = ref('')
const formFdTo = ref('')
const formFdAccount = ref('')
const formFdWebhookUrl = ref('')
const formFdWebhookToken = ref('')
const formEnabled = ref(true)

// Sort
const sortCol = ref('next_run')
const sortAsc = ref(true)

// Cron explain
const cronExplainHuman = ref('Enter a 5-field cron expression to preview')
const cronExplainValid = ref(false)
const cronExplainInvalid = ref(false)
const cronExplainUpcoming = ref<Date[]>([])
let previewTimer: ReturnType<typeof setTimeout> | null = null

// Detail panel
const runs = ref<CronRun[]>([])
const runsLoading = ref(false)

// Delete modal
const deleteModalOpen = ref(false)
const deleteTarget = ref<CronJob | null>(null)

// Tick
let tickInterval: ReturnType<typeof setInterval> | null = null
let unsubRunFinished: (() => void) | null = null
let reloadTimer: ReturnType<typeof setTimeout> | null = null
const now = ref(Date.now())

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const enabledCount = computed(() => jobs.value.filter(j => j.enabled).length)
const pausedCount = computed(() => jobs.value.length - enabledCount.value)
const reminderCount = computed(() => jobs.value.filter(j => (j.payloadKind || j.payload_kind) === 'reminder').length)
const agentTaskCount = computed(() => jobs.value.filter(j => (j.payloadKind || j.payload_kind) === 'agent_turn').length)

const upcomingJobs = computed(() => {
  return jobs.value
    .filter(j => isUpcomingRun(j))
    .map(j => ({ job: j, ts: new Date(j.next_run!).getTime() }))
    .sort((a, b) => a.ts - b.ts)
})

const nextJob = computed(() => upcomingJobs.value[0] || null)

const nextCountdown = computed(() => {
  if (!nextJob.value) return '—'
  return humanCountdown(new Date(nextJob.value.ts))
})

const nextRunHint = computed(() => {
  if (!nextJob.value) return 'no upcoming runs'
  return `${nextJob.value.job.name || nextJob.value.job.id} &middot; ${humanTime(new Date(nextJob.value.ts))}`
})

const last24h = computed(() => {
  return jobs.value.reduce((acc, j) => {
    const ts = j.last_run ? new Date(j.last_run) : null
    if (ts && !isNaN(ts.getTime()) && Date.now() - ts.getTime() < 24 * 3600 * 1000) {
      acc.runs += 1
      if (j.last_status === 'ok' || j.last_status === 'success') acc.ok += 1
      if (j.last_status === 'error' || j.last_status === 'fail') acc.err += 1
    }
    return acc
  }, { runs: 0, ok: 0, err: 0 })
})

const upcomingHorizon = computed(() => {
  const n = Date.now()
  return jobs.value
    .filter(j => isUpcomingRun(j))
    .map(j => ({ job: j, ts: new Date(j.next_run!).getTime() }))
    .filter(o => o.ts > n && (o.ts - n) < 12 * 3600 * 1000)
    .sort((a, b) => a.ts - b.ts)
})

const filteredSortedJobs = computed(() => {
  const st = searchText.value.toLowerCase()
  const filtered = jobs.value.filter(j => {
    if (!st) return true
    return (j.name || '').toLowerCase().includes(st) ||
      (j.message || j.prompt || '').toLowerCase().includes(st) ||
      (j.payloadKind || '').toLowerCase().includes(st) ||
      ((j.sessionTarget || j.session_target || '') + '').toLowerCase().includes(st) ||
      (j.expression || j.schedule || '').toLowerCase().includes(st)
  })
  return [...filtered].sort((a, b) => {
    let va: unknown = a[sortCol.value as keyof CronJob] ?? ''
    let vb: unknown = b[sortCol.value as keyof CronJob] ?? ''
    if (sortCol.value === 'next_run' || sortCol.value === 'last_run') {
      const da = va ? new Date(va as string).getTime() : (sortAsc.value ? Infinity : -Infinity)
      const db = vb ? new Date(vb as string).getTime() : (sortAsc.value ? Infinity : -Infinity)
      va = da; vb = db
    } else {
      va = String(va).toLowerCase()
      vb = String(vb).toLowerCase()
    }
    const cmp = (va as number | string) < (vb as number | string) ? -1 : (va as number | string) > (vb as number | string) ? 1 : 0
    return sortAsc.value ? cmp : -cmp
  })
})

const selectedJob = computed(() => jobs.value.find(j => j.id === selectedId.value) || null)

const tableCols = [
  { key: 'name', label: 'Name' },
  { key: 'payloadKind', label: 'Kind' },
  { key: 'sessionTarget', label: 'Target' },
  { key: 'expression', label: 'Schedule' },
  { key: 'enabled', label: 'Status' },
  { key: 'last_run', label: 'Last Run' },
  { key: 'next_run', label: 'Next Run' },
  { key: '_actions', label: '' },
]
const sortableCols = ['name', 'payloadKind', 'sessionTarget', 'expression', 'last_run', 'next_run']

const jobModeHint = computed(() => {
  if (formPayloadKind.value === 'system_event') {
    return 'System events append text to the agent main session and wake the heartbeat.'
  }
  if (formPayloadKind.value === 'reminder') {
    return 'Static reminders deliver this message directly; no model call or scheduled agent turn is created.'
  }
  return 'Agent tasks run as scheduled turns and use the selected session target.'
})

const sessionTargetHint = computed(() => {
  if (formPayloadKind.value === 'system_event') {
    return 'Main is locked for system events. Use Static Reminder for direct reminders.'
  }
  if (formPayloadKind.value === 'reminder') {
    return 'Static reminders run isolated and deliver back to the originating chat when one is available.'
  }
  if (formSessionTarget.value === 'current') {
    return 'The scheduled agent task continues in the active chat session.'
  }
  if (formSessionTarget.value === 'isolated') {
    return 'The scheduled agent task runs in its own cron session, separate from Main.'
  }
  if (formSessionTarget.value === 'session') {
    return 'The scheduled agent task continues in the named session key.'
  }
  return 'Choose where this background agent task keeps its conversation context.'
})

const showTargetSessionRow = computed(() => {
  if (formPayloadKind.value !== 'agent_turn') return false
  return formSessionTarget.value === 'current' || formSessionTarget.value === 'session'
})

const targetSessionLabel = computed(() => {
  return formSessionTarget.value === 'current' ? 'Current session key' : 'Named session key'
})

const targetSessionHint = computed(() => {
  if (formSessionTarget.value === 'current') {
    return 'Current is bound to the active WebChat session key when the job is saved.'
  }
  return 'Use a full session key from the chat header.'
})

const messageLabel = computed(() => {
  if (formPayloadKind.value === 'system_event') return 'Event text'
  if (formPayloadKind.value === 'reminder') return 'Reminder text'
  return 'Task prompt'
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
  tickInterval = setInterval(tick, 1000)

  rpc.waitForConnection()
    .then(() => rpc.call('cron.subscribe', {}))
    .catch(() => { /* subscription is best-effort */ })

  unsubRunFinished = rpc.on('cron.run.finished', () => {
    scheduleReload()
  })
})

onUnmounted(() => {
  if (tickInterval) { clearInterval(tickInterval); tickInterval = null }
  if (previewTimer) { clearTimeout(previewTimer); previewTimer = null }
  if (reloadTimer) { clearTimeout(reloadTimer); reloadTimer = null }
  if (unsubRunFinished) { unsubRunFinished(); unsubRunFinished = null }

  rpc.call('cron.unsubscribe', {}).catch(() => {})
})

watch(selectedId, (id) => {
  if (id) loadRuns(id)
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
    const data = await rpc.call<{ jobs?: CronJob[] } | CronJob[]>('cron.list')
    jobs.value = Array.isArray(data) ? data : (data.jobs || [])
  } catch (err) {
    console.warn('Failed to load cron jobs: ' + (err instanceof Error ? err.message : String(err)))
  }
}

function scheduleReload() {
  loadData()
  if (reloadTimer) clearTimeout(reloadTimer)
  reloadTimer = setTimeout(loadData, 750)
}

async function loadRuns(jobId: string) {
  runsLoading.value = true
  try {
    const data = await rpc.call<{ runs?: CronRun[] } | CronRun[]>('cron.runs', { id: jobId, limit: 10 })
    runs.value = Array.isArray(data) ? data : (data.runs || [])
  } catch {
    runs.value = []
  } finally {
    runsLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function toggleSelected(id: string) {
  selectedId.value = selectedId.value === id ? null : id
}

function onHorizonClick(id: string) {
  selectedId.value = id
  nextTick(() => {
    const card = document.querySelector(`[data-cron-row="${CSS.escape(id)}"]`)
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

function openRunChat(sessionKey: string) {
  router.push('/chat?session=' + encodeURIComponent(sessionKey))
}

function onSort(col: string) {
  if (sortCol.value === col) {
    sortAsc.value = !sortAsc.value
  } else {
    sortCol.value = col
    sortAsc.value = true
  }
}

async function toggleJob(job: CronJob) {
  try {
    await rpc.call('cron.update', { id: job.id, enabled: !job.enabled })
    console.warn(`Job ${job.enabled ? 'paused' : 'resumed'}`)
    loadData()
  } catch (err) {
    console.warn('Update failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

function isJobRunning(id: string): boolean {
  return runningJobIds.value.has(id)
}

async function runJob(id: string) {
  runningJobIds.value = new Set(runningJobIds.value).add(id)
  try {
    const res = await rpc.call<{ reply?: string; error?: string }>('cron.run', { id })
    if (res && res.reply) {
      console.warn(`Run complete: ${res.reply.substring(0, 120)}`)
    } else if (res && res.error) {
      console.warn(`Run failed: ${res.error}`)
    } else {
      console.warn('Job triggered')
    }
  } catch (err) {
    console.warn('Run failed: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    const next = new Set(runningJobIds.value)
    next.delete(id)
    runningJobIds.value = next
  }
}

function deleteJob(job: CronJob) {
  deleteTarget.value = job
  deleteModalOpen.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  try {
    await rpc.call('cron.remove', { id: deleteTarget.value.id })
    console.warn('Job deleted')
    if (selectedId.value === deleteTarget.value.id) selectedId.value = null
    loadData()
  } catch (err) {
    console.warn('Delete failed: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    deleteModalOpen.value = false
    deleteTarget.value = null
  }
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

function openPanel(job: CronJob | null, template?: PanelTemplate) {
  editingJob.value = job
  panelOpen.value = true

  const tpl = template || {}
  const payloadKind = job ? (job.payloadKind || 'agent_turn') : (tpl.payloadKind || 'reminder')
  const sessionTarget = job
    ? (job.sessionTarget || job.session_target || 'isolated')
    : (tpl.sessionTarget || (payloadKind === 'system_event' ? 'main' : 'isolated'))

  formName.value = job ? (job.name || '') : (tpl.name || '')
  formMessage.value = job ? (job.message || job.prompt || '') : (tpl.message || '')
  formType.value = job ? (job.scheduleKind || job.schedule_kind || 'cron') : (tpl.scheduleKind || tpl.schedule_kind || 'cron')
  formCron.value = job ? (job.expression || '') : (tpl.expression || '')
  formEnabled.value = job ? !!job.enabled : true
  formAgentId.value = job ? (job.agentId || 'main') : (tpl.agentId || 'main')
  formPayloadKind.value = payloadKind
  formSessionTarget.value = sessionTarget
  formTargetSessionKey.value = job ? jobSessionKey(job) : (tpl.targetSessionKey || activeChatSessionKey() || '')
  formEvery.value = formType.value === 'every'
    ? (job ? (job.scheduleRaw || job.schedule_raw || '') : String(tpl.every_seconds || ''))
    : ''
  formAt.value = formType.value === 'at'
    ? (job ? (job.scheduleRaw || job.schedule_raw || '') : (tpl.at || ''))
    : ''
  formTz.value = job ? (job.tz || '') : (tpl.tz || '')
  formWakeMode.value = job ? (job.wakeMode || job.wake_mode || 'now') : (tpl.wakeMode || 'now')

  populateDeliveryFields(job)
  onPayloadKindChange()
  onDeliveryModeChange()
  onFdModeChange()
  renderCronExplain(formCron.value)

  nextTick(() => {
    const input = document.getElementById('cp-name') as HTMLInputElement | null
    if (input) input.focus()
  })
}

function closePanel() {
  panelOpen.value = false
  editingJob.value = null
}

function populateDeliveryFields(job: CronJob | null) {
  const d = (job && job.delivery) || {}
  const mode = (d.mode || '').toLowerCase()
  formDeliveryMode.value =
    mode === 'webhook' ? 'webhook'
    : mode === 'announce' || mode === 'channel' ? 'announce'
    : mode === 'none' ? 'none'
    : ''
  formDeliveryChannel.value = d.channelName || ''
  formDeliveryTo.value = d.to || (d as Record<string, string>).channelId || ''
  formDeliveryAccount.value = d.accountId || ''
  formDeliveryWebhookUrl.value = d.webhookUrl || ''
  formDeliveryWebhookToken.value = ''
  formDeliveryBestEffort.value = !!d.bestEffort

  const fd = d.failureDestination || {}
  const fdMode = (fd.mode || '').toLowerCase()
  formFdMode.value =
    fdMode === 'webhook' ? 'webhook'
    : fdMode === 'channel' || fdMode === 'announce' ? 'channel'
    : ''
  formFdChannel.value = fd.channelName || ''
  formFdTo.value = fd.to || (fd as Record<string, string>).channelId || ''
  formFdAccount.value = fd.accountId || ''
  formFdWebhookUrl.value = fd.webhookUrl || ''
  formFdWebhookToken.value = ''
}

function onPayloadKindChange() {
  if (formPayloadKind.value === 'system_event') {
    formSessionTarget.value = 'main'
  } else if (formPayloadKind.value === 'reminder') {
    formSessionTarget.value = 'isolated'
  } else {
    const active = activeChatSessionKey()
    if (active && !formTargetSessionKey.value.trim()) {
      formTargetSessionKey.value = active
    }
    if (formSessionTarget.value === 'current' && !formTargetSessionKey.value.trim()) {
      formTargetSessionKey.value = active || jobSessionKey(editingJob.value)
    }
  }
}

function onSessionTargetChange() {
  if (formPayloadKind.value !== 'agent_turn') return
  if (formSessionTarget.value === 'current' && !formTargetSessionKey.value.trim()) {
    formTargetSessionKey.value = activeChatSessionKey() || jobSessionKey(editingJob.value)
  }
}

function onDeliveryModeChange() {
  // v-show handles visibility
}

function onFdModeChange() {
  // v-show handles visibility
}

function applyPreset(cron: string) {
  formCron.value = cron
  renderCronExplain(cron)
  nextTick(() => {
    const input = document.getElementById('cp-cron') as HTMLInputElement | null
    if (input) input.focus()
  })
}

function onCronInput() {
  renderCronExplain(formCron.value)
}

function buildDeliveryFromForm(): DeliveryConfig | null | undefined {
  const mode = formDeliveryMode.value
  const fdMode = formFdMode.value
  const bestEffort = formDeliveryBestEffort.value
  if (!mode && !fdMode) return null

  const fd = buildFailureDestinationFromForm()
  if (fd === undefined) return undefined

  if (mode === 'none') {
    const out: DeliveryConfig = { mode: 'none' }
    if (fd) out.failureDestination = fd
    return out
  }
  if (mode === 'webhook') {
    const url = formDeliveryWebhookUrl.value.trim()
    if (!url) { console.warn('Webhook URL is required for webhook delivery'); return undefined }
    const out: DeliveryConfig = { mode: 'webhook', webhookUrl: url }
    const tok = formDeliveryWebhookToken.value.trim()
    if (tok) out.webhookToken = tok
    if (bestEffort) out.bestEffort = true
    if (fd) out.failureDestination = fd
    return out
  }
  if (mode === 'announce') {
    const out: DeliveryConfig = { mode: 'announce' }
    const ch = formDeliveryChannel.value.trim()
    const to = formDeliveryTo.value.trim()
    const acct = formDeliveryAccount.value.trim()
    if (ch) out.channelName = ch.toLowerCase()
    if (to) out.to = to
    if (acct) out.accountId = acct
    if (bestEffort) out.bestEffort = true
    if (fd) out.failureDestination = fd
    return out
  }
  if (fd) return { failureDestination: fd }
  return null
}

function buildFailureDestinationFromForm(): FailureDestination | null | undefined {
  const mode = formFdMode.value
  if (!mode) return null
  if (mode === 'webhook') {
    const url = formFdWebhookUrl.value.trim()
    if (!url) { console.warn('Failure-destination webhook URL is required'); return undefined }
    const out: FailureDestination = { mode: 'webhook', webhookUrl: url }
    const tok = formFdWebhookToken.value.trim()
    if (tok) out.webhookToken = tok
    return out
  }
  const ch = formFdChannel.value.trim()
  const to = formFdTo.value.trim()
  const acct = formFdAccount.value.trim()
  if (!ch && !to) {
    console.warn('Failure destination channel needs a channel or recipient')
    return undefined
  }
  const out: FailureDestination = { mode: 'channel' }
  if (ch) out.channelName = ch.toLowerCase()
  if (to) out.to = to
  if (acct) out.accountId = acct
  return out
}

async function saveJob() {
  const name = formName.value.trim()
  if (!name) { console.warn('Name is required'); return }
  const type = formType.value
  const message = formMessage.value.trim()
  const enabled = formEnabled.value
  const payloadKind = formPayloadKind.value
  const agentId = formAgentId.value.trim() || 'main'
  const sessionTarget = payloadKind === 'system_event'
    ? 'main'
    : payloadKind === 'reminder'
      ? 'isolated'
      : formSessionTarget.value
  const targetSessionKey = formTargetSessionKey.value.trim()

  const payload: Record<string, unknown> = { name, enabled, payloadKind, agentId, sessionTarget, text: message }
  if (type === 'cron') {
    payload.schedule = { kind: 'cron', expr: formCron.value.trim() }
  } else if (type === 'every') {
    const everySeconds = Number(formEvery.value)
    if (!Number.isInteger(everySeconds) || everySeconds < 1) {
      console.warn('Interval must be an integer number of seconds')
      return
    }
    payload.schedule = { kind: 'every', every_seconds: everySeconds }
  } else if (type === 'at') {
    const at = formAt.value.trim()
    if (!at) { console.warn('ISO time is required'); return }
    payload.schedule = { kind: 'at', at }
  }

  const tz = formTz.value.trim()
  if (tz) {
    payload.tz = tz
    const sched = payload.schedule as Record<string, unknown>
    if (sched && sched.kind === 'cron') sched.tz = tz
  }

  const wakeMode = formWakeMode.value
  if (wakeMode && wakeMode !== 'now') payload.wakeMode = wakeMode

  const delivery = buildDeliveryFromForm()
  if (delivery === undefined) return
  if (delivery !== null) payload.delivery = delivery

  if (sessionTarget === 'current') {
    const boundSessionKey = targetSessionKey || activeChatSessionKey() || jobSessionKey(editingJob.value)
    if (!boundSessionKey) { console.warn('Current session key is required'); return }
    payload.sessionKey = boundSessionKey
    payload.targetSessionKey = boundSessionKey
    payload.originSessionKey = boundSessionKey
  }
  if (payloadKind === 'reminder' && activeChatSessionKey()) {
    payload.originSessionKey = activeChatSessionKey()
  }
  if (sessionTarget === 'session') {
    if (!targetSessionKey) { console.warn('Named session key is required'); return }
    payload.targetSessionKey = targetSessionKey
  }

  const isEdit = !!editingJob.value
  if (isEdit) payload.id = editingJob.value!.id

  const method = isEdit ? 'cron.update' : 'cron.create'
  try {
    await rpc.call(method, payload)
    console.warn(isEdit ? 'Schedule updated' : 'Schedule created')
    closePanel()
    loadData()
  } catch (err) {
    console.warn('Save failed: ' + (err instanceof Error ? err.message : String(err)))
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isUpcomingRun(j: CronJob, t = Date.now()) {
  if (!j || !j.enabled || !j.next_run) return false
  if (j.status === 'running') return false
  const ts = new Date(j.next_run)
  return !isNaN(ts.getTime()) && ts.getTime() > t
}

function nextRunText(j: CronJob) {
  if (!j || !j.enabled) return '—'
  if (j.status === 'running') return 'running'
  if (!j.next_run) return '—'
  const ts = new Date(j.next_run)
  if (isNaN(ts.getTime())) return '—'
  if (ts.getTime() <= Date.now()) return 'awaiting update'
  return humanCountdown(ts)
}

function nextRunAbs(j: CronJob) {
  if (!j || !j.enabled || j.status === 'running' || !j.next_run) return ''
  const ts = new Date(j.next_run)
  if (isNaN(ts.getTime()) || ts.getTime() <= Date.now()) return ''
  return humanTime(ts)
}

function dotClass(j: CronJob) {
  if (!j.enabled) return 'is-off'
  const lastStatus = j.last_status || (j.last_run ? 'ok' : null)
  if (lastStatus === 'error' || lastStatus === 'fail') return 'is-error'
  return 'is-on'
}

function jobKindLabel(j: CronJob) {
  const kind = j.payloadKind || j.payload_kind
  if (kind === 'reminder') return 'Reminder'
  if (kind === 'system_event') return 'System event'
  return 'Agent task'
}

function jobKindClass(j: CronJob) {
  const kind = j.payloadKind || j.payload_kind
  return kind === 'reminder' ? 'is-reminder' : 'is-agent'
}

function isImminent(j: CronJob) {
  if (!j || !j.next_run) return false
  const left = new Date(j.next_run).getTime() - Date.now()
  return left > 0 && left < 60_000
}

function horizonLeft(ts: number) {
  const span = 12 * 3600 * 1000
  const left = ((ts - Date.now()) / span) * 100
  return Math.max(0, Math.min(100, left)) + '%'
}

function horizonTickLabel(h: number) {
  const ts = Date.now() + h * 3600 * 1000
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function tick() {
  now.value = Date.now()
}

// ---------------------------------------------------------------------------
// Cron parsing
// ---------------------------------------------------------------------------

interface ParsedField {
  all: boolean
  set?: Set<number>
}

interface ParsedCron {
  minute: ParsedField
  hour: ParsedField
  dom: ParsedField
  month: ParsedField
  dow: ParsedField
  raw: string
}

function parseField(field: string, min: number, max: number, names?: Record<string, number>): ParsedField {
  if (field === '*' || field === '?') return { all: true }
  const out = new Set<number>()
  field.split(',').forEach(part => {
    let stepStr = '1'
    let core = part
    const slash = part.indexOf('/')
    if (slash >= 0) { core = part.slice(0, slash); stepStr = part.slice(slash + 1) }
    const step = Math.max(1, parseInt(stepStr, 10) || 1)
    let lo: number | null = min, hi: number | null = max
    if (core === '*' || core === '') { lo = min; hi = max }
    else if (core.includes('-')) {
      const [a, b] = core.split('-')
      lo = toNum(a, names)
      hi = toNum(b, names)
    } else {
      const n = toNum(core, names)
      lo = hi = n
    }
    if (lo === null || hi === null || lo > max || hi < min) return
    lo = Math.max(min, lo); hi = Math.min(max, hi)
    for (let v = lo; v <= hi; v += step) out.add(v)
  })
  return { all: false, set: out }
}

function toNum(token: string | null, names?: Record<string, number>): number | null {
  if (token == null) return null
  const t = String(token).trim().toLowerCase()
  if (t === '') return null
  if (names && names[t] !== undefined) return names[t]
  const n = parseInt(t, 10)
  if (Number.isNaN(n)) return null
  return n
}

function parseCron(expr: string): ParsedCron | null {
  if (!expr) return null
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return null
  const monthNames: Record<string, number> = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 }
  const dowNames: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 }
  try {
    const minute = parseField(parts[0], 0, 59)
    const hour = parseField(parts[1], 0, 23)
    const dom = parseField(parts[2], 1, 31)
    const month = parseField(parts[3], 1, 12, monthNames)
    let dow = parseField(parts[4], 0, 6, dowNames)
    if (!dow.all && dow.set!.has(7)) { dow.set!.delete(7); dow.set!.add(0) }
    return { minute, hour, dom, month, dow, raw: expr }
  } catch { return null }
}

function matches(field: ParsedField, v: number) { return field.all || field.set!.has(v) }

function nextRuns(parsed: ParsedCron, count: number, fromTs?: number): Date[] {
  if (!parsed) return []
  const results: Date[] = []
  const start = new Date(fromTs || Date.now())
  start.setSeconds(0, 0)
  start.setMinutes(start.getMinutes() + 1)
  let d = new Date(start)
  const endLimit = Date.now() + 365 * 24 * 3600 * 1000
  while (results.length < count && d.getTime() < endLimit) {
    const m = d.getMinutes()
    const h = d.getHours()
    const dom = d.getDate()
    const mon = d.getMonth() + 1
    const dow = d.getDay()
    const domAll = parsed.dom.all
    const dowAll = parsed.dow.all
    const dayOk = (domAll && dowAll) ? true
      : (domAll ? matches(parsed.dow, dow)
        : (dowAll ? matches(parsed.dom, dom)
          : (matches(parsed.dom, dom) || matches(parsed.dow, dow))))
    if (
      matches(parsed.minute, m) &&
      matches(parsed.hour, h) &&
      matches(parsed.month, mon) &&
      dayOk
    ) {
      results.push(new Date(d))
    }
    d = new Date(d.getTime() + 60_000)
  }
  return results
}

function humanizeFieldList(field: ParsedField, all_label: string, names?: Record<number, string>) {
  if (field.all) return all_label
  const arr = [...field.set!].sort((a, b) => a - b)
  if (arr.length === 0) return '—'
  const display = arr.map(v => names ? names[v] : String(v).padStart(2, '0'))
  if (display.length === 1) return display[0]
  if (display.length <= 4) return display.join(', ')
  return display.slice(0, 3).join(', ') + ` & ${display.length - 3} more`
}

function explainCron(expr: string): string {
  const p = parseCron(expr)
  if (!p) return ''
  const dowNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const monNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  if (p.minute.all && p.hour.all) return 'Every minute'
  if (!p.minute.all && p.minute.set!.size === 1 && p.hour.all) {
    const m = [...p.minute.set!][0]
    return `Every hour at :${String(m).padStart(2, '0')}`
  }
  if (p.minute.all === false && p.minute.set!.size === 1 && p.hour.all === false && p.hour.set!.size === 1) {
    const m = [...p.minute.set!][0], h = [...p.hour.set!][0]
    const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
    if (p.dom.all && p.dow.all && p.month.all) return `Every day at ${time}`
    if (p.dow.all === false && p.dom.all && p.month.all) {
      const days = [...p.dow.set!].sort((a, b) => a - b).map(v => dowNames[v])
      if (days.length === 5 && days[0] === 'Mon' && days[4] === 'Fri') return `Weekdays at ${time}`
      if (days.length === 2 && days.includes('Sat') && days.includes('Sun')) return `Weekends at ${time}`
      return `${days.join(', ')} at ${time}`
    }
    if (p.dom.all === false && p.dow.all && p.month.all) {
      const days = [...p.dom.set!].sort((a, b) => a - b).join(', ')
      return `Day ${days} of every month at ${time}`
    }
    if (p.dom.all === false && p.dow.all && p.month.all === false) {
      const months = [...p.month.set!].sort((a, b) => a - b).map(v => monNames[v]).join(', ')
      const days = [...p.dom.set!].sort((a, b) => a - b).join(', ')
      return `${months} ${days} at ${time}`
    }
  }
  if (!p.minute.all && p.minute.set!.size > 1 && p.hour.all) {
    const arr = [...p.minute.set!].sort((a, b) => a - b)
    const diffs = arr.slice(1).map((v, i) => v - arr[i])
    if (diffs.length && diffs.every(d => d === diffs[0]) && arr[0] % diffs[0] === 0) {
      return `Every ${diffs[0]} minutes`
    }
  }

  const minPart = humanizeFieldList(p.minute, 'every minute')
  const hourPart = humanizeFieldList(p.hour, 'every hour')
  return `at minute ${minPart}, hour ${hourPart}`
}

function renderCronExplain(expr: string) {
  const trimmed = (expr || '').trim()
  if (!trimmed) {
    cronExplainValid.value = false
    cronExplainInvalid.value = false
    cronExplainHuman.value = 'Enter a 5-field cron expression to preview'
    cronExplainUpcoming.value = []
    return
  }
  const parsed = parseCron(trimmed)
  if (!parsed) {
    cronExplainValid.value = false
    cronExplainInvalid.value = true
    cronExplainHuman.value = 'Could not parse expression — expected 5 fields (m h dom mon dow).'
    cronExplainUpcoming.value = []
    return
  }
  const summary = explainCron(trimmed) || 'matches a custom cadence'
  cronExplainInvalid.value = false
  cronExplainValid.value = true
  cronExplainHuman.value = summary
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    const next = nextRuns(parsed, 3)
    cronExplainUpcoming.value = next
  }, 60)
}

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

function humanCountdown(date: Date): string {
  const diff = date.getTime() - Date.now()
  if (diff < 0) {
    const past = -diff
    return formatDuration(past) + ' ago'
  }
  if (diff < 1000) return 'now'
  return 'in ' + formatDuration(diff)
}

function humanCountdownPast(date: Date): string {
  const diff = Date.now() - date.getTime()
  if (diff < 0) return 'in ' + formatDuration(-diff)
  if (diff < 1000) return 'just now'
  return formatDuration(diff) + ' ago'
}

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  if (m < 60) return m + 'm ' + (s % 60) + 's'
  const h = Math.floor(m / 60)
  if (h < 24) return h + 'h ' + (m % 60) + 'm'
  const d = Math.floor(h / 24)
  return d + 'd ' + (h % 24) + 'h'
}

function humanTime(date: Date): string {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const tomorrow = new Date(today.getTime() + 86400000)
  const dayAfter = new Date(today.getTime() + 2 * 86400000)
  const t = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (date >= today && date < tomorrow) return `today ${t}`
  if (date >= tomorrow && date < dayAfter) return `tomorrow ${t}`
  return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ' ' + t
}

// ---------------------------------------------------------------------------
// Session helpers
// ---------------------------------------------------------------------------

function activeChatSessionKey(): string {
  const routeSession = typeof route.query.session === 'string' ? canonicalSessionKey(route.query.session) : ''
  if (routeSession) return routeSession
  try {
    return canonicalSessionKey(localStorage.getItem('opensquilla_active_session') || '')
  } catch { return '' }
}

function canonicalSessionKey(key: string): string {
  const value = (key || '').trim()
  if (!value) return ''
  if (value === 'default' || value === 'webchat:default') {
    return 'agent:main:webchat:default'
  }
  if (value.startsWith('agent:default:')) {
    return 'agent:main:' + value.slice('agent:default:'.length)
  }
  if (value.startsWith('sess-')) return 'agent:main:webchat:' + value.slice('sess-'.length)
  return value
}

function jobSessionKey(job: CronJob | null): string {
  if (!job) return ''
  return (
    job.originSessionKey ||
    job.origin_session_key ||
    job.targetSessionKey ||
    job.target_session_key ||
    job.sessionKey ||
    job.session_key ||
    ''
  )
}
</script>

<style scoped>
.cron-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  max-width: none;
  position: relative;
}

.cron-stage__header {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  justify-content: space-between;
  padding-top: var(--sp-3);
}

.cron-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.cron-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  margin: 0;
  position: relative;
}

.cron-stage__title::after {
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
  bottom: -8px;
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  width: 36px;
}

.cron-stage__subtitle {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: var(--sp-3) 0 0;
}

.cron-stage__eyebrow {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.cron-stage__actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.cron-search-wrap {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  gap: 8px;
  padding: 0 12px;
}

.cron-search-icon {
  color: var(--text-dim);
}

.cron-search-input {
  background: transparent;
  border: none;
  color: var(--text);
  font-size: var(--fs-sm);
  min-width: 180px;
  outline: none;
  padding: 8px 0;
}

.cron-summary {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  overflow: hidden;
  padding: var(--sp-4);
  position: relative;
}

.stat--hero {
  min-height: 116px;
}

.stat-label {
  color: var(--text-dim);
  display: block;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.08em;
  line-height: 1.25;
  text-transform: uppercase;
}

.stat-value {
  align-items: center;
  display: flex;
  font-size: 2rem;
  font-variant-numeric: tabular-nums;
  gap: 8px;
  letter-spacing: 0;
  line-height: 1.12;
  margin-top: var(--sp-4);
}

.stat-total {
  color: var(--text-muted);
  font-size: 1rem;
  font-weight: 400;
}

.stat-hint {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin-top: var(--sp-2);
}

.stat__chip {
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  padding: 2px 8px;
}

.stat__chip--info {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.stat__chip--accent {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.cron-pos { color: var(--ok); }
.cron-neg { color: var(--danger); }

/* Horizon */
.cron-horizon {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
}

.cron-horizon__head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  margin-bottom: var(--sp-3);
}

.cron-horizon__title {
  font-size: var(--fs-sm);
  font-weight: 600;
}

.cron-horizon__legend {
  align-items: center;
  color: var(--text-muted);
  display: inline-flex;
  font-size: 11px;
  gap: 6px;
}

.cron-horizon__dot {
  background: var(--accent);
  border-radius: 50%;
  display: inline-block;
  height: 8px;
  width: 8px;
}

.cron-horizon__rail {
  height: 32px;
  position: relative;
}

.cron-horizon__marker {
  align-items: center;
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  display: flex;
  padding: 0;
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
}

.cron-horizon__marker-dot {
  background: var(--accent);
  border-radius: 50%;
  height: 10px;
  width: 10px;
}

.cron-horizon__marker-tip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: none;
  font-size: 11px;
  left: 50%;
  padding: 6px 10px;
  position: absolute;
  top: -8px;
  transform: translate(-50%, -100%);
  white-space: nowrap;
  z-index: 10;
}

.cron-horizon__marker:hover .cron-horizon__marker-tip {
  display: block;
}

.cron-horizon__marker-tip strong {
  display: block;
  font-size: 12px;
}

.cron-horizon__marker-tip em {
  color: var(--text-muted);
  font-style: normal;
}

.cron-horizon__axis {
  border-top: 1px solid var(--border);
  height: 20px;
  margin-top: var(--sp-2);
  position: relative;
}

.cron-horizon__tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
}

.cron-horizon__tick-line {
  background: var(--border);
  display: block;
  height: 6px;
  margin: 0 auto;
  width: 1px;
}

.cron-horizon__tick-label {
  color: var(--text-dim);
  display: block;
  font-size: 10px;
  margin-top: 2px;
  text-align: center;
}

/* Jobs list */
.cron-jobs__head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.cron-jobs__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.cron-jobs__count {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  margin-left: 6px;
  padding: 2px 8px;
}

.cron-view-toggle {
  display: flex;
  gap: 2px;
}

.cron-view-toggle__btn {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: 4px 12px;
}

.cron-view-toggle__btn.is-active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

/* Cards */
.cron-card-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
}

.cron-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  overflow: hidden;
  padding: var(--sp-4);
  position: relative;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.cron-card:hover {
  border-color: var(--accent);
}

.cron-card.is-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.cron-card.is-imminent {
  animation: cron-pulse 2s infinite;
}

@keyframes cron-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(var(--accent-rgb, 240, 160, 48), 0.3); }
  50% { box-shadow: 0 0 0 4px rgba(var(--accent-rgb, 240, 160, 48), 0); }
}

.cron-card__head {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
}

.cron-card__dot {
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
  height: 10px;
  width: 10px;
}

.cron-card__dot.is-on { background: var(--ok); }
.cron-card__dot.is-off { background: var(--text-dim); }
.cron-card__dot.is-error { background: var(--danger); }

.cron-card__name {
  background: none;
  border: none;
  color: var(--text);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  overflow: hidden;
  padding: 0;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cron-card__name:hover {
  color: var(--accent);
}

.cron-pill {
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  margin-left: auto;
  padding: 2px 8px;
  text-transform: uppercase;
}

.cron-pill--is-reminder {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.cron-pill--is-agent {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.cron-card__schedule {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.cron-expr {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 2px 8px;
}

.cron-expr--inline {
  background: transparent;
  border: none;
  padding: 0;
}

.cron-card__human {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.cron-card__meta {
  display: grid;
  gap: var(--sp-2);
  margin: 0;
}

.cron-card__meta > div {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.cron-card__meta dt {
  color: var(--text-dim);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.25;
}

.cron-card__meta dd {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 0;
}

.cron-mono {
  font-family: var(--font-mono);
}

.cron-muted {
  color: var(--text-dim);
}

.cron-card__abs {
  color: var(--text-dim);
  font-size: 11px;
}

.cron-card__message {
  grid-column: 1 / -1;
}

.cron-card__message dd {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
}

.cron-card__actions {
  display: flex;
  gap: 4px;
  margin-top: auto;
  padding-top: var(--sp-2);
}

.cron-iconbtn {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  gap: 4px;
  padding: 4px 8px;
  font-size: 12px;
}

.cron-iconbtn:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
  color: var(--text);
}

.cron-iconbtn:disabled {
  cursor: wait;
  opacity: 0.72;
}

.cron-iconbtn--accent:hover {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  color: var(--accent);
}

.cron-iconbtn--danger:hover {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

.cron-iconbtn--sm {
  padding: 2px 6px;
}

/* Table */
.cron-table-wrap {
  overflow-x: auto;
}

.cron-table {
  border-collapse: collapse;
  font-size: var(--fs-sm);
  width: 100%;
}

.cron-table th,
.cron-table td {
  border-bottom: 1px solid var(--border);
  padding: 10px 12px;
  text-align: left;
  vertical-align: middle;
}

.cron-table th {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cron-th-sort {
  cursor: pointer;
  user-select: none;
}

.cron-th-sort:hover {
  color: var(--text);
}

.cron-table__arrow {
  color: var(--accent);
}

.cron-table tr.is-selected td {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.cron-table__actions {
  display: flex;
  gap: 2px;
  white-space: nowrap;
}

.cron-link {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  padding: 0;
  text-decoration: underline;
}

.cron-link:hover {
  color: var(--text);
}

/* Status */
.status {
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  text-transform: uppercase;
}

.status--ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.status--err {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

.status--off {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-dim);
}

/* Empty state */
.state {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}

.state-icon {
  color: var(--text-dim);
}

.state-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.state-text {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
  max-width: 520px;
}

.cron-empty__clock {
  color: var(--text-dim);
  height: 120px;
  width: 120px;
}

.cron-empty__clock svg {
  height: 100%;
  width: 100%;
}

.cron-empty__ring {
  animation: cron-spin 60s linear infinite;
  transform-origin: center;
}

.cron-empty__hand {
  animation: cron-spin 12s linear infinite;
  transform-origin: 60px 60px;
}

@keyframes cron-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.cron-empty__title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.cron-empty__msg {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
}

.cron-empty__cta {
  align-items: center;
  display: inline-flex;
  gap: 6px;
}

.cron-empty__hints {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.cron-empty__hints-label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cron-empty-hint {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  cursor: pointer;
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  text-align: left;
  width: 100%;
}

.cron-empty-hint:hover {
  border-color: var(--accent);
}

.cron-empty-hint code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 2px 8px;
  white-space: nowrap;
}

.cron-empty-hint span {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

/* Panel */
.cron-panel-overlay {
  bottom: 0;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1000;
}

.cron-panel__scrim {
  background: rgba(0, 0, 0, 0.4);
  bottom: 0;
  left: 0;
  opacity: 0;
  position: fixed;
  right: 0;
  top: 0;
  transition: opacity 0.22s;
}

.cron-panel__scrim.is-open {
  opacity: 1;
}

.cron-panel {
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  bottom: 0;
  display: flex;
  flex-direction: column;
  max-width: 480px;
  position: fixed;
  right: 0;
  top: 0;
  transform: translateX(100%);
  transition: transform 0.22s ease-out;
  width: 100%;
  z-index: 1001;
}

.cron-panel.is-open {
  transform: translateX(0);
}

.cron-panel__head {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  padding: var(--sp-4);
}

.cron-panel__eyebrow {
  color: var(--text-dim);
  display: block;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.cron-panel__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
}

.cron-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4);
}

.cron-panel__actions {
  display: flex;
  gap: var(--sp-3);
  margin-top: var(--sp-4);
}

/* Form fields */
.cron-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: var(--sp-3);
}

.cron-field__label {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.cron-field__input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  font-size: var(--fs-sm);
  padding: 8px 12px;
  width: 100%;
}

.cron-field__input:focus {
  border-color: var(--accent);
  outline: none;
}

.cron-field__input--mono {
  font-family: var(--font-mono);
}

.cron-field__input--textarea {
  min-height: 80px;
  resize: vertical;
}

.cron-field__hint {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.5;
}

/* Cron explain */
.cron-explain {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
}

.cron-explain.is-valid {
  border-color: var(--ok);
}

.cron-explain.is-invalid {
  border-color: var(--danger);
}

.cron-explain__human {
  color: var(--text);
  font-size: var(--fs-sm);
  font-weight: 500;
}

.cron-explain__hint {
  color: var(--text-dim);
  font-size: 12px;
  margin-top: 4px;
}

.cron-explain__upcoming {
  list-style: none;
  margin: var(--sp-2) 0 0;
  padding: 0;
}

.cron-explain__upcoming li {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  padding: 2px 0;
}

.cron-explain__num {
  color: var(--text-dim);
  font-size: 11px;
  min-width: 18px;
}

.cron-explain__abs {
  color: var(--text-dim);
  font-size: 11px;
}

/* Presets */
.cron-presets {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--sp-2);
}

.cron-presets__label {
  color: var(--text-dim);
  font-size: 11px;
}

.cron-preset {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 8px;
}

.cron-preset:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* Advanced */
.cron-advanced {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: var(--sp-3);
}

.cron-advanced__summary {
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-sm);
  font-weight: 500;
  padding: var(--sp-3);
  user-select: none;
}

.cron-advanced__body {
  border-top: 1px solid var(--border);
  padding: var(--sp-3);
}

.cron-advanced--nested {
  margin-top: var(--sp-3);
}

/* Toggle */
.cron-toggle {
  align-items: center;
  cursor: pointer;
  display: inline-flex;
  gap: 10px;
  margin-bottom: var(--sp-3);
}

.cron-toggle input {
  display: none;
}

.cron-toggle__track {
  background: var(--border);
  border-radius: 12px;
  display: inline-block;
  height: 20px;
  position: relative;
  transition: background 0.15s;
  width: 36px;
}

.cron-toggle input:checked + .cron-toggle__track {
  background: var(--accent);
}

.cron-toggle__thumb {
  background: #fff;
  border-radius: 50%;
  display: block;
  height: 16px;
  left: 2px;
  position: absolute;
  top: 2px;
  transition: transform 0.15s;
  width: 16px;
}

.cron-toggle input:checked + .cron-toggle__track .cron-toggle__thumb {
  transform: translateX(16px);
}

.cron-toggle__label {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

/* Spinner */
.cron-spinner {
  animation: cron-spin 1s linear infinite;
  border: 2px solid var(--border);
  border-radius: 50%;
  border-top-color: var(--accent);
  display: inline-block;
  height: 14px;
  width: 14px;
}

/* Modal */
.modal-overlay {
  align-items: center;
  background: rgba(0, 0, 0, 0.5);
  bottom: 0;
  display: flex;
  justify-content: center;
  left: 0;
  position: fixed;
  right: 0;
  top: 0;
  z-index: 1100;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  max-width: 420px;
  padding: var(--sp-5);
  width: 90%;
}

.modal__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0 0 var(--sp-3);
}

.modal__body {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin-bottom: var(--sp-4);
}

.modal__footer {
  display: flex;
  gap: var(--sp-3);
  justify-content: flex-end;
}

/* Transitions */
.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.2s;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

/* Responsive */
@media (max-width: 980px) {
  .cron-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .cron-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .cron-card-grid {
    grid-template-columns: 1fr;
  }

  .cron-panel {
    max-width: 100%;
  }
}

@media (max-width: 480px) {
  .cron-summary {
    grid-template-columns: 1fr;
  }
}
</style>
