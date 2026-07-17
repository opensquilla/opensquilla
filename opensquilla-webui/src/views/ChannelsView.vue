<template>
  <div class="ch-stage control-stage">
    <header class="ch-stage__header control-stage__header">
      <div class="ch-stage__title-block control-stage__title-block">
        <h1 class="ch-stage__title control-stage__title">{{ t('console.channels.title') }}</h1>
        <p class="ch-stage__subtitle control-stage__subtitle">{{ t('console.channels.subtitle') }}</p>
      </div>
      <div class="ch-stage__actions control-stage__actions">
        <button class="btn btn--primary" type="button" @click="openChannelCompose">
          <Icon name="plus" :size="16" aria-hidden="true" />
          <span>{{ t('console.channels.addChannel') }}</span>
        </button>
        <button class="btn btn--ghost" type="button" :title="t('console.common.refresh')" :disabled="loading || refreshing" @click="manualRefresh">
          <Icon name="refresh" :size="16" aria-hidden="true" :class="{ 'is-spinning': refreshing }" />
          <span>{{ refreshing ? t('console.common.refreshing') : t('console.common.refresh') }}</span>
        </button>
      </div>
    </header>

    <p class="ch-context">
      <i18n-t keypath="console.channels.contextStrip" tag="span">
        <template #link>
          <router-link to="/settings/channels">{{ t('console.channels.contextStripLink') }}</router-link>
        </template>
      </i18n-t>
    </p>

    <section v-if="total > 0" class="ch-summary" :aria-label="t('console.channels.summaryLabel')">
      <button type="button" :class="['ch-summary__item', { 'is-active': statusFilter === 'all' }]" @click="statusFilter = 'all'">
        <strong>{{ total }}</strong><span>{{ t('console.channels.totalChannels') }}</span>
      </button>
      <button
        v-if="totalPendingPairings > 0"
        type="button"
        class="ch-summary__item tone-warn"
        :title="t('console.channels.pairings.pendingBadge', { count: totalPendingPairings })"
        @click="openFirstPendingPairings"
      >
        <span class="dot" aria-hidden="true"></span><strong>{{ totalPendingPairings }}</strong><span>{{ t('console.channels.pendingApproval') }}</span>
      </button>
      <button
        v-for="chip in summaryChips"
        :key="chip.key"
        type="button"
        :class="['ch-summary__item', `tone-${chip.tone}`, { 'is-active': statusFilter === chip.key }]"
        :aria-pressed="statusFilter === chip.key"
        @click="statusFilter = statusFilter === chip.key ? 'all' : chip.key"
      >
        <span class="dot" aria-hidden="true"></span><strong>{{ chip.count }}</strong><span>{{ chip.label }}</span>
      </button>
    </section>

    <section class="ch-toolbar" :aria-label="t('console.channels.filtersLabel')">
      <label class="ch-search">
        <span class="ch-sr-only">{{ t('console.channels.searchLabel') }}</span>
        <Icon name="search" :size="16" aria-hidden="true" />
        <input v-model="searchQuery" type="search" :placeholder="t('console.channels.searchPlaceholder')" />
      </label>
      <label class="ch-select">
        <span class="ch-sr-only">{{ t('console.channels.providerFilter') }}</span>
        <select v-model="providerFilter">
          <option value="all">{{ t('console.channels.allProviders') }}</option>
          <option v-for="provider in providers" :key="provider" :value="provider">{{ providerLabel(provider) }}</option>
        </select>
      </label>
      <span v-if="filteredChannels.length !== channels.length" class="ch-toolbar__result">
        {{ t('console.channels.filteredCount', { count: filteredChannels.length }) }}
      </span>
    </section>

    <PendingRestartBanner />

    <!-- A background refresh failure keeps the last-good rows and warns inline;
         the full-page error only stands in when the very first load fails. -->
    <p v-if="error && channels.length > 0" class="ch-stale" role="status">
      <Icon name="info" :size="15" aria-hidden="true" />
      <span>{{ t('console.channels.staleData', { time: lastUpdatedLabel }) }}</span>
      <button type="button" class="btn btn--ghost" @click="manualRefresh">{{ t('console.common.retry') }}</button>
    </p>

    <ErrorState v-if="error && channels.length === 0" :message="error" :on-retry="loadData" />

    <div v-else-if="loading && channels.length === 0" class="control-empty">
      <LoadingSpinner />
    </div>

    <section v-else-if="channels.length === 0" class="control-empty ch-empty">
      <div class="ch-empty__icon" aria-hidden="true"><Icon name="channels" :size="34" /></div>
      <div class="control-empty__title">{{ t('console.channels.emptyTitle') }}</div>
      <p class="control-empty__hint">{{ t('console.channels.emptyMsg') }}</p>
      <button class="btn btn--primary" type="button" @click="openChannelCompose">
        <Icon name="plus" :size="16" aria-hidden="true" />
        <span>{{ t('console.channels.addFirstChannel') }}</span>
      </button>
    </section>

    <section v-else class="ch-workspace" :class="{ 'has-detail': selectedChannel }">
      <p v-if="queryMissing" class="ch-query-missing" role="status">
        <span>{{ t('console.channels.queryNotFound', { name: selectedName }) }}</span>
        <button type="button" class="btn btn--ghost" @click="closeDetail">{{ t('console.channels.queryNotFoundDismiss') }}</button>
      </p>
      <div class="ch-table-wrap">
        <table class="ch-table">
          <thead>
            <tr>
              <th scope="col">{{ t('console.channels.provider') }}</th>
              <th scope="col">{{ t('console.channels.channel') }}</th>
              <th scope="col" class="ch-hide-mobile">{{ t('console.channels.transport') }}</th>
              <th scope="col">{{ t('console.channels.status') }}</th>
              <th v-if="!selectedChannel" scope="col" class="ch-hide-mobile">{{ t('console.channels.connectedSince') }}</th>
              <th scope="col"><span class="ch-sr-only">{{ t('console.channels.actions') }}</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ch in filteredChannels"
              :key="channelKey(ch)"
              :class="{ 'is-selected': selectedName === channelKey(ch) }"
              tabindex="0"
              @click="selectChannel(ch)"
              @keydown.enter="selectChannel(ch)"
              @keydown.space.prevent="selectChannel(ch)"
            >
              <td><span class="ch-provider-mark" aria-hidden="true">{{ providerInitial(ch.type) }}</span><span class="ch-provider-name">{{ providerLabel(ch.type) }}</span></td>
              <td>
                <strong>{{ ch.name || ch.id || t('console.channels.unknown') }}</strong>
                <button
                  v-if="(ch.pendingPairings || 0) > 0"
                  type="button"
                  class="ch-tab-badge ch-row-badge"
                  :aria-label="t('console.channels.pairings.pendingBadge', { count: ch.pendingPairings })"
                  :title="t('console.channels.pairings.pendingBadge', { count: ch.pendingPairings })"
                  @click.stop="openPairings(ch)"
                >{{ ch.pendingPairings }}</button>
              </td>
              <td class="ch-hide-mobile"><span class="ch-muted">{{ transportLabel(ch) }}</span></td>
              <td><ChannelStatusPill :status="ch.status" :enabled="ch.enabled" :pending-restart="pendingRestart.isPending(channelKey(ch))" :error-class="lastErrorClass(ch.diagnostics)" show-cause /></td>
              <td v-if="!selectedChannel" class="ch-hide-mobile"><span class="ch-mono ch-muted">{{ formatSince(ch.connected_since) }}</span></td>
              <td><Icon name="chevronRight" :size="15" aria-hidden="true" /></td>
            </tr>
            <tr v-if="filteredChannels.length === 0">
              <td colspan="6" class="ch-table__none">
                <span>{{ t('console.channels.noMatches') }}</span>
                <button v-if="hasActiveFilters" type="button" class="ch-inline-link" @click="clearFilters">{{ t('console.channels.clearFilters') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="unconfiguredChannels.length" class="ch-unconfigured">
          <h4>{{ t('console.channels.unconfiguredTitle') }}</h4>
          <p>{{ t('console.channels.unconfiguredHint') }}</p>
          <div v-for="ch in unconfiguredChannels" :key="channelKey(ch)" class="ch-unconfigured__row">
            <span class="ch-provider-mark" aria-hidden="true">{{ providerInitial(ch.type) }}</span>
            <strong>{{ ch.name || ch.id }}</strong>
            <span class="ch-muted">{{ providerLabel(ch.type) }}</span>
            <ChannelStatusPill :status="ch.status" :enabled="ch.enabled" :error-class="lastErrorClass(ch.diagnostics)" />
          </div>
        </div>
      </div>

      <!-- Below the split-view breakpoint the detail becomes a fixed overlay;
           the scrim dismisses it and gives the modal a backdrop. -->
      <div v-if="selectedChannel" class="ch-scrim" @click="closeDetail"></div>
      <aside v-if="selectedChannel" ref="detailRef" class="ch-detail" :aria-label="t('console.channels.detailLabel', { name: selectedChannel.name })" @keydown.esc="closeDetail">
        <header class="ch-detail__header">
          <div class="ch-detail__identity">
            <span class="ch-provider-mark is-large" aria-hidden="true">{{ providerInitial(selectedChannel.type) }}</span>
            <div>
              <div class="ch-detail__title-row">
                <h2>{{ selectedChannel.name }}</h2>
                <ChannelStatusPill :status="selectedChannel.status" :enabled="selectedChannel.enabled" :pending-restart="pendingRestart.isPending(channelKey(selectedChannel))" :error-class="lastErrorClass(selectedChannel.diagnostics)" />
              </div>
              <p>{{ providerLabel(selectedChannel.type) }} · {{ transportLabel(selectedChannel) }}</p>
            </div>
          </div>
          <button class="ch-icon-btn" type="button" :title="t('common.close')" @click="closeDetail"><Icon name="x" :size="18" /></button>
        </header>

        <!-- Actions grouped by consequence — observe/runtime ops, then
             configuration writes, with destructive Remove isolated at the far
             edge — so the row encodes the cost gradient instead of rendering
             five equal buttons. -->
        <div class="ch-detail__actions">
          <div class="ch-detail__actiongroup" role="group" :aria-label="t('console.channels.opsActionsLabel')">
            <button class="btn btn--ghost" type="button" :disabled="actionPending(selectedChannel, 'probe')" @click="probeChannel(selectedChannel)">
              <Icon name="gauge" :size="15" aria-hidden="true" />
              <span>{{ actionPending(selectedChannel, 'probe') ? t('console.channels.testing') : t('console.channels.testConnection') }}</span>
            </button>
            <button
              class="btn btn--ghost"
              type="button"
              :disabled="actionPending(selectedChannel, 'restart') || selectedChannel.enabled === false || !adapterLoaded(selectedChannel)"
              :title="selectedChannel.enabled !== false && !adapterLoaded(selectedChannel) ? t('console.channels.restartNotLoaded') : undefined"
              @click="restartChannel(selectedChannel)"
            >
              <Icon name="refresh" :size="15" aria-hidden="true" />
              <span>{{ t('console.channels.restart') }}</span>
            </button>
          </div>
          <span class="ch-detail__actionsep" aria-hidden="true"></span>
          <div class="ch-detail__actiongroup" role="group" :aria-label="t('console.channels.configActionsLabel')">
            <button class="btn btn--ghost" type="button" :title="t('console.channels.editActionHint')" @click="openChannelEdit(selectedChannel)">
              <Icon name="edit" :size="15" aria-hidden="true" />
              <span>{{ t('console.channels.edit') }}</span>
            </button>
            <button class="btn btn--ghost" type="button" :disabled="actionPending(selectedChannel, 'toggle')" :title="t('console.channels.configActionHint')" @click="toggleChannel(selectedChannel)">
              <span>{{ selectedChannel.enabled === false ? t('console.channels.enable') : t('console.channels.disable') }}</span>
            </button>
          </div>
          <button class="btn btn--ghost ch-detail__remove" type="button" :disabled="actionPending(selectedChannel, 'remove')" :title="t('console.channels.configActionHint')" @click="removeChannel(selectedChannel)">
            <span>{{ t('console.channels.removeChannel') }}</span>
          </button>
        </div>

        <nav class="ch-detail__tabs" role="tablist" :aria-label="t('console.channels.detailSections')">
          <button v-for="tab in DETAIL_TABS" :key="tab" type="button" role="tab" :aria-selected="detailTab === tab" :class="{ 'is-active': detailTab === tab }" @click="setDetailTab(tab)">
            {{ t(`console.channels.tabs.${tab}`) }}
            <span v-if="tab === 'pairings' && pendingPairingCount > 0" class="ch-tab-badge" :aria-label="t('console.channels.pairings.pendingBadge', { count: pendingPairingCount })">{{ pendingPairingCount }}</span>
          </button>
        </nav>

        <div class="ch-detail__body">
          <template v-if="detailTab === 'overview'">
            <div v-if="selectedProbe" :class="['ch-probe-result', probeToneClass(selectedProbe)]" role="status">
              <Icon :name="selectedProbe.status === 'verified' ? 'check' : 'info'" :size="17" aria-hidden="true" />
              <div>
                <strong>{{ probeTitle(selectedProbe) }}</strong>
                <p>{{ probeResultDetail(selectedChannel) }}</p>
                <button v-if="selectedProbe.status === 'failed'" class="btn btn--ghost ch-probe-result__edit" type="button" @click="openChannelEdit(selectedChannel)">
                  <Icon name="edit" :size="13" aria-hidden="true" />
                  <span>{{ t('console.channels.editCredentials') }}</span>
                </button>
              </div>
            </div>
            <section class="ch-panel">
              <h3>{{ t('console.channels.healthChecks') }}</h3>
              <div class="ch-check-row">
                <Icon name="shield" :size="18" />
                <div><strong>{{ t('console.channels.connection') }}</strong><span>{{ t('console.channels.connectionDescription') }}</span></div>
                <b v-if="selectedChannel.connected" class="is-ok">{{ t('console.channels.connectedShort') }}</b>
                <button v-else class="ch-inline-link" type="button" @click="probeChannel(selectedChannel)">{{ t('console.channels.verifyCredentials') }}</button>
              </div>
              <div class="ch-check-row"><Icon name="cloud" :size="18" /><div><strong>{{ t('console.channels.transport') }}</strong><span>{{ transportDescription(selectedChannel) }}</span></div><b :class="selectedChannel.connected ? 'is-ok' : 'is-muted'">{{ selectedChannel.connected ? t('console.channels.healthy') : statusText(selectedChannel) }}</b></div>
              <div class="ch-check-row" :class="{ 'is-warn-row': deliveryReview(selectedChannel).tone === 'warn' }">
                <Icon name="channels" :size="18" />
                <div><strong>{{ t('console.channels.durableDelivery') }}</strong><span>{{ deliveryReview(selectedChannel).detail }}</span></div>
                <b :class="deliveryReview(selectedChannel).tone === 'warn' ? 'is-warn' : 'is-ok'">{{ deliveryReview(selectedChannel).label }}</b>
              </div>
            </section>
            <section class="ch-panel ch-facts">
              <h3>{{ t('console.channels.runtime') }}</h3>
              <dl>
                <div><dt>{{ t('console.channels.connectedSince') }}</dt><dd>{{ formatSince(selectedChannel.connected_since) }}</dd></div>
                <div><dt>{{ t('console.channels.restartAttempts') }}</dt><dd>{{ selectedChannel.restart_attempts ?? 0 }}</dd></div>
                <div><dt>{{ t('console.channels.botIdentity') }}</dt><dd>{{ selectedChannel.bot_user_id || '—' }}</dd></div>
                <div v-if="maturityKey(selectedChannel) !== 'unrated'"><dt>{{ t('console.channels.maturity') }}</dt><dd>{{ maturityLabel(selectedChannel) }}</dd></div>
              </dl>
            </section>
          </template>

          <template v-else-if="detailTab === 'capabilities'">
            <section class="ch-panel">
              <div class="ch-panel__heading">
                <h3>{{ t('console.channels.worksTitle') }}</h3>
                <span v-if="maturityKey(selectedChannel) !== 'unrated'" class="ch-maturity" :title="t('console.channels.maturityHint')">{{ maturityLabel(selectedChannel) }}</span>
              </div>
              <p class="ch-panel__intro">{{ t('console.channels.worksHint') }}</p>
              <div v-if="platformRows(selectedChannel).length" class="ch-capabilities">
                <div v-for="row in platformRows(selectedChannel)" :key="row.category" class="ch-capability">
                  <Icon :name="row.tone === 'ok' ? 'check' : row.tone === 'warn' ? 'info' : 'x'" :size="15" :class="`is-${row.tone}`" />
                  <div><strong>{{ t(`console.channels.category.${row.category}`) }}</strong><span v-if="row.notes">{{ row.notes }}</span></div>
                  <span :class="['ch-proof', row.tone === 'ok' ? 'is-effective' : row.tone === 'warn' ? 'is-config' : 'is-declared']">{{ row.label }}</span>
                </div>
              </div>
              <p v-else class="ch-muted">{{ t('console.channels.noCapabilityEvidence') }}</p>
            </section>
            <details v-if="capabilityRows(selectedChannel).length" class="ch-tech">
              <summary>{{ t('console.channels.technicalDetails') }}</summary>
              <div class="ch-capabilities">
                <div v-for="capability in capabilityRows(selectedChannel)" :key="capability.name" class="ch-capability">
                  <Icon :name="capability.effective ? 'check' : 'info'" :size="15" />
                  <div><strong>{{ humanize(capability.name) }}</strong><span>{{ evidenceLabel(capability) }}</span></div>
                  <span :class="['ch-proof', capability.effective ? 'is-effective' : 'is-declared']">{{ capability.effective ? t('console.channels.implemented') : t('console.channels.declaredOnly') }}</span>
                </div>
              </div>
            </details>
          </template>

          <template v-else-if="detailTab === 'pairings'">
            <section class="ch-panel ch-pairings" :aria-busy="pairingsLoading">
              <div class="ch-panel__heading">
                <div>
                  <h3>{{ t('console.channels.pairings.title') }}</h3>
                  <p>{{ t('console.channels.pairings.description') }}</p>
                </div>
                <button
                  class="btn btn--ghost"
                  type="button"
                  :disabled="pairingsLoading"
                  @click="loadPairings(selectedChannel)"
                >
                  <Icon name="refresh" :size="14" aria-hidden="true" />
                  {{ t('console.channels.pairings.refresh') }}
                </button>
              </div>

              <div class="ch-pairing-summary" :aria-label="t('console.channels.pairings.summaryLabel')">
                <span><strong>{{ pendingPairings.length }}</strong> {{ t('console.channels.pairings.pending') }}</span>
                <span><strong>{{ approvedPairings.length }}</strong> {{ t('console.channels.pairings.approved') }}</span>
                <span v-if="revokedPairings.length"><strong>{{ revokedPairings.length }}</strong> {{ t('console.channels.pairings.revoked') }}</span>
              </div>
              <label v-if="pairings.length > 0" class="ch-pairing-search">
                <span class="ch-sr-only">{{ t('console.channels.pairings.searchLabel') }}</span>
                <Icon name="search" :size="15" aria-hidden="true" />
                <input v-model="pairingSearch" type="search" :placeholder="t('console.channels.pairings.searchPlaceholder')" />
              </label>

              <div v-if="pairingsLoading && pairings.length === 0" class="ch-pairing-state" role="status">
                <LoadingSpinner />
                <span>{{ t('console.channels.pairings.loading') }}</span>
              </div>
              <div v-else-if="pairingsError" class="ch-pairing-state is-error" role="alert">
                <Icon name="info" :size="17" aria-hidden="true" />
                <span>{{ pairingsError }}</span>
                <button class="btn btn--ghost" type="button" @click="loadPairings(selectedChannel)">
                  {{ t('console.channels.pairings.tryAgain') }}
                </button>
              </div>
              <div v-else-if="pairings.length === 0" class="ch-pairing-state">
                <Icon name="shield" :size="20" aria-hidden="true" />
                <strong>{{ t('console.channels.pairings.emptyTitle') }}</strong>
                <span>{{ t('console.channels.pairings.emptyDescription') }}</span>
              </div>
              <div v-else class="ch-pairing-groups">
                <section v-if="pendingPairings.length" :aria-label="t('console.channels.pairings.pendingRequests')">
                  <h4>{{ t('console.channels.pairings.pendingRequests') }}</h4>
                  <article v-for="pairing in pendingPairings" :key="pairing.pairingId" class="ch-pairing-row">
                    <div class="ch-pairing-avatar" aria-hidden="true">{{ pairingInitial(pairing) }}</div>
                    <div class="ch-pairing-identity">
                      <strong>{{ pairing.senderName || pairing.senderId }}</strong>
                      <span class="ch-mono">{{ pairing.senderId }}</span>
                      <span v-if="pairing.pairingCode" class="ch-mono ch-pairing-code">{{ t('console.channels.pairings.requestCode', { code: pairing.pairingCode }) }}</span>
                      <time v-if="pairing.createdAt" :datetime="pairing.createdAt">{{ t('console.channels.pairings.requestedAt', { time: formatSince(pairing.createdAt) }) }}</time>
                    </div>
                    <span class="ch-pairing-status is-pending">{{ t('console.channels.pairings.pending') }}</span>
                    <button
                      class="btn btn--primary"
                      type="button"
                      :disabled="pairingActionPending(selectedChannel, pairing, 'approve')"
                      :aria-label="t('console.channels.pairings.approveLabel', { sender: pairing.senderName || pairing.senderId })"
                      @click="approvePairing(selectedChannel, pairing)"
                    >
                      {{ pairingActionPending(selectedChannel, pairing, 'approve') ? t('console.channels.pairings.approving') : t('console.channels.pairings.approve') }}
                    </button>
                  </article>
                </section>

                <section v-if="approvedPairings.length" :aria-label="t('console.channels.pairings.approvedAccess')">
                  <h4>{{ t('console.channels.pairings.approvedAccess') }}</h4>
                  <article v-for="pairing in approvedPairings" :key="pairing.pairingId" class="ch-pairing-row">
                    <div class="ch-pairing-avatar" aria-hidden="true">{{ pairingInitial(pairing) }}</div>
                    <div class="ch-pairing-identity">
                      <strong>{{ pairing.senderName || pairing.senderId }}</strong>
                      <span class="ch-mono">{{ pairing.senderId }}</span>
                      <time v-if="pairing.approvedAt" :datetime="pairing.approvedAt">{{ t('console.channels.pairings.approvedAt', { time: formatSince(pairing.approvedAt) }) }}</time>
                    </div>
                    <span class="ch-pairing-status is-approved">{{ t('console.channels.pairings.approved') }}</span>
                    <button
                      class="btn btn--ghost ch-pairing-revoke"
                      type="button"
                      :disabled="pairingActionPending(selectedChannel, pairing, 'revoke')"
                      :aria-label="t('console.channels.pairings.revokeLabel', { sender: pairing.senderName || pairing.senderId })"
                      @click="revokePairing(selectedChannel, pairing)"
                    >
                      {{ pairingActionPending(selectedChannel, pairing, 'revoke') ? t('console.channels.pairings.revoking') : t('console.channels.pairings.revoke') }}
                    </button>
                  </article>
                </section>

                <section v-if="revokedPairings.length" :aria-label="t('console.channels.pairings.revokedAccess')">
                  <h4>{{ t('console.channels.pairings.revokedAccess') }}</h4>
                  <article v-for="pairing in revokedPairings" :key="pairing.pairingId" class="ch-pairing-row">
                    <div class="ch-pairing-avatar" aria-hidden="true">{{ pairingInitial(pairing) }}</div>
                    <div class="ch-pairing-identity">
                      <strong>{{ pairing.senderName || pairing.senderId }}</strong>
                      <span class="ch-mono">{{ pairing.senderId }}</span>
                    </div>
                    <span class="ch-pairing-status is-revoked">{{ t('console.channels.pairings.revoked') }}</span>
                    <button
                      class="btn btn--ghost"
                      type="button"
                      :disabled="pairingActionPending(selectedChannel, pairing, 'reapprove')"
                      :aria-label="t('console.channels.pairings.reapproveLabel', { sender: pairing.senderName || pairing.senderId })"
                      @click="approvePairing(selectedChannel, pairing)"
                    >
                      {{ pairingActionPending(selectedChannel, pairing, 'reapprove') ? t('console.channels.pairings.approving') : t('console.channels.pairings.reapprove') }}
                    </button>
                  </article>
                </section>
              </div>
              <p class="ch-sr-only" role="status" aria-live="polite">{{ pairingAnnouncement }}</p>
            </section>
          </template>

          <template v-else-if="detailTab === 'diagnostics'">
            <section v-if="lastError(selectedChannel)" class="ch-alert is-danger">
              <Icon name="info" :size="18" /><div><strong>{{ t('console.channels.lastError') }}</strong><p>{{ lastError(selectedChannel) }}</p></div>
            </section>
            <section class="ch-panel">
              <h3>{{ t('console.channels.messageDelivery') }}</h3>
              <div class="ch-metrics">
                <div><strong>{{ deliveryCount(selectedChannel, 'ingress', 'accepted') }}</strong><span>{{ t('console.channels.acceptedIngress') }}</span></div>
                <div><strong>{{ deliveryCount(selectedChannel, 'ingress', 'processing') }}</strong><span>{{ t('console.channels.processingIngress') }}</span></div>
                <div><strong>{{ deliveryCount(selectedChannel, 'outbox', 'sent') }}</strong><span>{{ t('console.channels.confirmedOutbound') }}</span></div>
                <div :class="{ 'is-warn': deliveryCount(selectedChannel, 'outbox', 'unknown') > 0 }"><strong>{{ deliveryCount(selectedChannel, 'outbox', 'unknown') }}</strong><span>{{ t('console.channels.needsReview') }}</span></div>
              </div>
            </section>
            <section class="ch-panel ch-facts">
              <h3>{{ t('console.channels.connectionOwner') }}</h3>
              <dl>
                <div><dt>{{ t('console.channels.owner') }}</dt><dd>{{ ownerSummary(selectedChannel) }}</dd></div>
                <div v-if="probeResults[channelKey(selectedChannel)]"><dt>{{ t('console.channels.lastTest') }}</dt><dd>{{ probeResults[channelKey(selectedChannel)]?.status }}</dd></div>
              </dl>
            </section>
          </template>

          <template v-else>
            <section class="ch-panel">
              <div class="ch-panel__heading"><h3>{{ t('console.channels.savedConfiguration') }}</h3><button class="btn btn--ghost" type="button" @click="openChannelEdit(selectedChannel)"><Icon name="edit" :size="14" />{{ t('console.channels.editInSettings') }}</button></div>
              <p class="ch-panel__intro">{{ t('console.channels.secretRedactionHint') }}</p>
              <LoadingSpinner v-if="configLoading" />
              <p v-else-if="configError" class="ch-alert-text">{{ configError }}</p>
              <dl v-else-if="selectedConfig" class="ch-config-list">
                <div v-for="field in configRows(selectedConfig)" :key="field.key"><dt>{{ humanize(field.key) }}</dt><dd :class="{ 'is-secret': field.secret }">{{ field.value }}</dd></div>
              </dl>
              <p v-else class="ch-muted">{{ t('console.channels.selectConfigurationHint') }}</p>
            </section>
          </template>
        </div>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import ChannelStatusPill from '@/components/ChannelStatusPill.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import PendingRestartBanner from '@/components/PendingRestartBanner.vue'
import { useRequest } from '@/composables/useRequest'
import { usePendingRestart } from '@/composables/usePendingRestart'
import { useToasts } from '@/composables/useToasts'
import { useConfirm } from '@/composables/useConfirm'
import {
  CHANNEL_STATUS_ORDER,
  CHANNEL_STATUS_TONES,
  adapterLoaded,
  lastErrorClass,
  statusPresentation,
  type ChannelStatusKey,
} from '@/lib/channelStatus'

interface CapabilityEvidence {
  declared?: boolean
  implemented?: boolean
  effective?: boolean
  evidence_kind?: string
  methods?: string[]
  proof_status?: string
}

interface Channel {
  name?: string
  id?: string
  type?: string
  status?: string
  connected?: boolean
  connected_since?: string | number | null
  restart_attempts?: number
  pendingPairings?: number
  bot_user_id?: string | null
  enabled?: boolean
  configured?: boolean
  capabilities?: string[]
  capability_profile?: {
    transports?: string[]
    maturity?: string
    evidence?: Record<string, CapabilityEvidence>
  } | null
  diagnostics?: Record<string, unknown>
  [key: string]: unknown
}

interface ProbeResult {
  status: string
  connected: boolean
  latencyMs?: number | null
  detail?: string
  result?: Record<string, unknown>
}

interface ChannelsStatusResponse { channels?: Channel[] }
interface ChannelPairing {
  pairingId: string
  pairingCode?: string
  channelName: string
  senderId: string
  senderName?: string | null
  status: 'pending' | 'approved' | string
  createdAt?: string | null
  approvedAt?: string | null
}

interface PairingsResponse { pairings?: ChannelPairing[] }
type DetailTab = 'overview' | 'pairings' | 'capabilities' | 'diagnostics' | 'configuration'
type StatusFilter = 'all' | ChannelStatusKey

const STATUS_SEVERITY = Object.fromEntries(
  CHANNEL_STATUS_ORDER.map((key, index) => [key, index]),
) as Record<ChannelStatusKey, number>
const DETAIL_TABS: DetailTab[] = ['overview', 'pairings', 'capabilities', 'diagnostics', 'configuration']
const SECRET_MARKER = '***'

const { t } = useI18n()
const rpc = useRpcStore()
const router = useRouter()
const route = useRoute()
const { pushToast } = useToasts()
const { confirm } = useConfirm()
const pendingRestart = usePendingRestart()
const searchQuery = ref('')
const providerFilter = ref('all')
const statusFilter = ref<StatusFilter>('all')
const selectedName = ref('')
const detailTab = ref<DetailTab>('overview')
const detailRef = ref<HTMLElement | null>(null)
// Focus returns here when the (overlay) detail closes.
let detailInvoker: HTMLElement | null = null
const pendingActions = ref(new Set<string>())
const probeResults = ref<Record<string, ProbeResult>>({})
const selectedConfig = ref<Record<string, unknown> | null>(null)
const selectedSecretFields = ref<string[]>([])
const configLoading = ref(false)
const configError = ref('')
const pairings = ref<ChannelPairing[]>([])
const pairingsLoading = ref(false)
const pairingsError = ref('')
const pairingAnnouncement = ref('')
let pairingsRequestId = 0

const { data: channelsData, loading, error, execute, refresh } = useRequest<ChannelsStatusResponse>(
  'channels.status', undefined, { immediate: false, errorLabel: t('console.channels.loadFailed') },
)

const channels = computed<Channel[]>(() => {
  const raw = (channelsData.value?.channels || []).filter(ch => ch && ch.configured !== false)
  return [...raw].sort(
    (a, b) => STATUS_SEVERITY[presentationFor(a).key] - STATUS_SEVERITY[presentationFor(b).key],
  )
})
// Channels running in this gateway process but absent from config — surfaced
// separately so an operator can see (and remove) an orphaned runtime channel.
const unconfiguredChannels = computed<Channel[]>(() =>
  (channelsData.value?.channels || []).filter(ch => ch && ch.configured === false))
const total = computed(() => channels.value.length)
// One chip per unified state actually present — chip words match row pills exactly.
const summaryChips = computed(() => {
  const counts = new Map<ChannelStatusKey, number>()
  for (const ch of channels.value) {
    const key = presentationFor(ch).key
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return CHANNEL_STATUS_ORDER
    .filter(key => (counts.get(key) || 0) > 0)
    .map(key => ({
      key,
      count: counts.get(key) || 0,
      tone: CHANNEL_STATUS_TONES[key],
      label: key === 'unknown' ? t('console.channels.unknown') : t(`channelStatus.${key}`),
    }))
})
const providers = computed(() => [...new Set(channels.value.map(ch => String(ch.type || 'unknown')))].sort())
const selectedChannel = computed(() => channels.value.find(ch => channelKey(ch) === selectedName.value) || null)
const selectedProbe = computed(() =>
  selectedChannel.value ? probeResults.value[channelKey(selectedChannel.value)] : undefined)
const hasActiveFilters = computed(() =>
  Boolean(searchQuery.value.trim()) || providerFilter.value !== 'all' || statusFilter.value !== 'all')
function clearFilters(): void {
  searchQuery.value = ''
  providerFilter.value = 'all'
  statusFilter.value = 'all'
}
const filteredChannels = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return channels.value.filter(ch => {
    if (providerFilter.value !== 'all' && ch.type !== providerFilter.value) return false
    if (statusFilter.value !== 'all' && presentationFor(ch).key !== statusFilter.value) return false
    return !query || [ch.name, ch.id, ch.type, ch.status].some(value => String(value || '').toLowerCase().includes(query))
  })
})
const pairingSearch = ref('')
function matchesPairingSearch(pairing: ChannelPairing): boolean {
  const query = pairingSearch.value.trim().toLowerCase()
  if (!query) return true
  return [pairing.senderName, pairing.senderId, pairing.pairingCode]
    .some(value => String(value || '').toLowerCase().includes(query))
}
const pendingPairings = computed(() =>
  pairings.value.filter(pairing => pairing.status === 'pending' && matchesPairingSearch(pairing)))
const approvedPairings = computed(() =>
  pairings.value.filter(pairing => pairing.status === 'approved' && matchesPairingSearch(pairing)))
const revokedPairings = computed(() =>
  pairings.value.filter(pairing => pairing.status === 'revoked' && matchesPairingSearch(pairing)))
// Unfiltered pending count drives the tab badge (a filtered-out request still
// awaits the operator).
const totalPendingPairings = computed(() =>
  channels.value.reduce((sum, ch) => sum + (ch.pendingPairings || 0), 0))

function openPairings(ch: Channel): void {
  if (selectedName.value !== channelKey(ch)) selectChannel(ch)
  setDetailTab('pairings')
}

function openFirstPendingPairings(): void {
  const target = channels.value.find(ch => (ch.pendingPairings || 0) > 0)
  if (target) openPairings(target)
}

const pendingPairingCount = computed(() =>
  pairings.value.filter(pairing => pairing.status === 'pending').length)

const loadData = refresh
let pollTimer: ReturnType<typeof setInterval> | null = null
let unsubs: Array<() => void> = []
let activatedOnce = false
const refreshing = ref(false)
const lastUpdatedAt = ref<number | null>(null)
const lastUpdatedLabel = computed(() =>
  lastUpdatedAt.value ? new Date(lastUpdatedAt.value).toLocaleTimeString() : '—')

async function manualRefresh(): Promise<void> {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await refresh()
    if (!error.value) lastUpdatedAt.value = Date.now()
  } finally {
    refreshing.value = false
  }
}

function teardownLive() {
  unsubs.forEach(unsub => unsub())
  unsubs = []
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  document.removeEventListener('keydown', onDocumentKeydown)
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && selectedName.value) closeDetail()
}

onActivated(() => {
  applyDetailQuery()
  if (!activatedOnce) { activatedOnce = true; void execute() } else { void refresh() }
  unsubs = [rpc.on('channel.status', () => { void refresh() })]
  pollTimer = setInterval(() => {
    void refresh().then(() => { if (!error.value) lastUpdatedAt.value = Date.now() })
  }, 30000)
  document.addEventListener('keydown', onDocumentKeydown)
  lastUpdatedAt.value = Date.now()
})
onDeactivated(teardownLive)
onUnmounted(teardownLive)

function openChannelCompose(): void {
  void router.push({ path: '/settings/channels', hash: '#channel-new' })
}

function openChannelEdit(ch: Channel): void {
  const name = channelKey(ch)
  // A channel literally named "new" collides with the reserved compose hash.
  if (name === 'new') { void router.push('/settings/channels'); return }
  void router.push({ path: '/settings/channels', hash: `#channel-${encodeURIComponent(name)}` })
}
function channelKey(ch: Channel): string { return String(ch.name || ch.id || ch.type || 'unknown') }

function presentationFor(ch: Channel) {
  return statusPresentation({
    status: ch.status,
    enabled: ch.enabled,
    connected: ch.connected,
    pendingRestart: pendingRestart.isPending(channelKey(ch)),
    errorClass: lastErrorClass(ch.diagnostics),
  })
}

function statusText(ch: Channel): string {
  const pres = presentationFor(ch)
  return pres.key === 'unknown' ? t(pres.labelKey, { raw: pres.raw || '—' }) : t(pres.labelKey)
}

// Clear pending-restart entries the moment a status snapshot proves the
// restart happened. Reconcile against RAW rows (incl. configured:false).
watch(channelsData, data => {
  pendingRestart.reconcile(data?.channels || [])
})

function selectChannel(ch: Channel): void {
  // Re-clicking the selected row toggles the aside closed instead of silently
  // resetting the tab and discarding loaded pairings/config.
  if (selectedName.value === channelKey(ch)) {
    closeDetail()
    return
  }
  pairingsRequestId += 1
  detailInvoker = document.activeElement instanceof HTMLElement ? document.activeElement : null
  selectedName.value = channelKey(ch)
  detailTab.value = 'overview'
  selectedConfig.value = null
  selectedSecretFields.value = []
  configError.value = ''
  pairings.value = []
  pairingSearch.value = ''
  pairingsLoading.value = false
  pairingsError.value = ''
  pairingAnnouncement.value = ''
  // When the detail is an overlay (narrow viewport), move focus into it so a
  // keyboard user lands in the dialog; the scrim + Esc close it.
  void nextTick(() => {
    if (window.matchMedia('(max-width: 1180px)').matches) {
      detailRef.value?.querySelector<HTMLElement>('button, [href], input, select, [tabindex]')?.focus()
    }
  })
}

function closeDetail(): void {
  const invoker = detailInvoker
  selectedName.value = ''
  detailInvoker = null
  void nextTick(() => invoker?.focus())
}

// ?channel=<name>&tab=<tab> keeps the aside URL-addressable: F5/relaunch
// restores the selection, and links can target a specific channel and tab.
const queryMissing = computed(() =>
  Boolean(selectedName.value) && !loading.value && channels.value.length > 0 && !selectedChannel.value)

function applyDetailQuery(): void {
  const name = typeof route.query.channel === 'string' ? route.query.channel : ''
  const tab = typeof route.query.tab === 'string' ? route.query.tab : ''
  if (name && name !== selectedName.value) {
    selectedName.value = name
    detailTab.value = DETAIL_TABS.includes(tab as DetailTab) ? (tab as DetailTab) : 'overview'
  } else if (name && DETAIL_TABS.includes(tab as DetailTab)) {
    detailTab.value = tab as DetailTab
  }
}

watch([selectedName, detailTab], () => {
  if (route.path !== '/channels') return
  const query = { ...route.query }
  if (selectedName.value) {
    query.channel = selectedName.value
    query.tab = detailTab.value
  } else {
    delete query.channel
    delete query.tab
  }
  void router.replace({ query })
})

async function removeChannel(ch: Channel): Promise<void> {
  const name = channelKey(ch)
  const ok = await confirm({
    title: t('setup.channels.removeConfirmTitle'),
    body: t('setup.channels.removeConfirmBody', { name }),
    primaryLabel: t('setup.channels.removeConfirmPrimary'),
  })
  if (!ok) return
  await withAction(ch, 'remove', async () => {
    try {
      const res = await rpc.call<{ changed?: boolean; restartRequired?: boolean }>('onboarding.channel.remove', { name })
      if (res?.changed !== false && res?.restartRequired !== false) pendingRestart.record(name, 'remove')
      pushToast(t(res?.restartRequired === false ? 'setup.toast.channelRemovedLive' : 'setup.toast.channelRemoved'), { tone: 'ok' })
      closeDetail()
      await refresh()
    } catch (err) {
      pushToast(errorMessage(err), { tone: 'danger' })
    }
  })
}

function setDetailTab(tab: DetailTab): void {
  detailTab.value = tab
  if (tab === 'configuration' && selectedChannel.value && !selectedConfig.value && !configLoading.value) {
    void loadConfiguration(selectedChannel.value)
  }
  if (tab === 'pairings' && selectedChannel.value && !pairingsLoading.value) {
    void loadPairings(selectedChannel.value)
  }
}

async function withAction(ch: Channel, action: string, run: () => Promise<void>): Promise<void> {
  const key = `${channelKey(ch)}:${action}`
  if (pendingActions.value.has(key)) return
  pendingActions.value = new Set(pendingActions.value).add(key)
  try { await run() } finally {
    const next = new Set(pendingActions.value)
    next.delete(key)
    pendingActions.value = next
  }
}

function actionPending(ch: Channel, action: string): boolean { return pendingActions.value.has(`${channelKey(ch)}:${action}`) }

function pairingActionKey(ch: Channel, pairing: ChannelPairing, action: string): string {
  return `pairing:${channelKey(ch)}:${pairing.pairingId}:${action}`
}

function pairingActionPending(ch: Channel, pairing: ChannelPairing, action: string): boolean {
  return pendingActions.value.has(pairingActionKey(ch, pairing, action))
}

async function withPairingAction(ch: Channel, pairing: ChannelPairing, action: string, run: () => Promise<void>): Promise<void> {
  const key = pairingActionKey(ch, pairing, action)
  if (pendingActions.value.has(key)) return
  pendingActions.value = new Set(pendingActions.value).add(key)
  try { await run() } finally {
    const next = new Set(pendingActions.value)
    next.delete(key)
    pendingActions.value = next
  }
}

async function loadPairings(ch: Channel): Promise<void> {
  const name = channelKey(ch)
  const requestId = ++pairingsRequestId
  pairingsLoading.value = true
  pairingsError.value = ''
  try {
    const result = await rpc.call<PairingsResponse>('channels.pairings', { channelName: name })
    if (selectedName.value !== name || requestId !== pairingsRequestId) return
    pairings.value = (result.pairings || []).filter(pairing => pairing.channelName === name)
  } catch (err) {
    if (selectedName.value === name && requestId === pairingsRequestId) {
      pairingsError.value = t('console.channels.pairings.loadFailed', { error: errorMessage(err) })
    }
  } finally {
    if (selectedName.value === name && requestId === pairingsRequestId) pairingsLoading.value = false
  }
}

async function approvePairing(ch: Channel, pairing: ChannelPairing): Promise<void> {
  const sender = pairing.senderName || pairing.senderId
  const confirmed = await confirm({
    title: t('console.channels.pairings.approveConfirmTitle'),
    body: t('console.channels.pairings.approveConfirmBody', { sender, channel: channelKey(ch) }),
    primaryLabel: t('console.channels.pairings.approve'),
    primaryClass: 'btn--primary',
  })
  if (!confirmed) return
  await withPairingAction(ch, pairing, pairing.status === 'revoked' ? 'reapprove' : 'approve', async () => {
    pairingsError.value = ''
    try {
      await rpc.call('channels.pairing.approve', { channelName: channelKey(ch), pairingId: pairing.pairingId })
      pairingAnnouncement.value = t('console.channels.pairings.approveSuccess', { sender })
      pushToast(pairingAnnouncement.value, { tone: 'ok' })
      await loadPairings(ch)
    } catch (err) {
      pairingsError.value = t('console.channels.pairings.approveFailed', { sender, error: errorMessage(err) })
    }
  })
}

async function revokePairing(ch: Channel, pairing: ChannelPairing): Promise<void> {
  const sender = pairing.senderName || pairing.senderId
  const confirmed = await confirm({
    title: t('console.channels.pairings.revokeConfirmTitle'),
    body: t('console.channels.pairings.revokeConfirmBody', { sender, channel: channelKey(ch) }),
    primaryLabel: t('console.channels.pairings.revoke'),
  })
  if (!confirmed) return
  await withPairingAction(ch, pairing, 'revoke', async () => {
    pairingsError.value = ''
    try {
      await rpc.call('channels.pairing.revoke', { channelName: channelKey(ch), pairingId: pairing.pairingId })
      pairingAnnouncement.value = t('console.channels.pairings.revokeSuccess', { sender })
      pushToast(pairingAnnouncement.value, { tone: 'ok' })
      await loadPairings(ch)
    } catch (err) {
      pairingsError.value = t('console.channels.pairings.revokeFailed', { sender, error: errorMessage(err) })
    }
  })
}

// Branch on the probe's three-way status, not the connected boolean: a bad
// token must read as a failure, not as "probe unavailable".
async function probeChannel(ch: Channel): Promise<void> {
  await withAction(ch, 'probe', async () => {
    try {
      const result = await rpc.call<ProbeResult>('channels.probe', { name: channelKey(ch) })
      probeResults.value = { ...probeResults.value, [channelKey(ch)]: result }
      if (result.status === 'verified') {
        pushToast(t('console.channels.toastProbePassed', { name: channelKey(ch), ms: result.latencyMs ?? 0 }), { tone: 'ok' })
      } else if (result.status === 'failed') {
        pushToast(t('console.channels.toastProbeFailedResult', { name: channelKey(ch), detail: result.detail || t('console.channels.probeNoDetail') }), { tone: 'danger' })
      } else {
        pushToast(t('console.channels.toastProbeUnsupported', { name: channelKey(ch) }), { tone: 'info' })
      }
    } catch (err) {
      pushToast(t('console.channels.toastProbeFailed', { name: channelKey(ch), error: errorMessage(err) }), { tone: 'danger' })
    }
  })
}

function probeToneClass(probe: ProbeResult): string {
  if (probe.status === 'verified') return 'is-ok'
  return probe.status === 'failed' ? 'is-danger' : 'is-muted'
}

function probeTitle(probe: ProbeResult): string {
  if (probe.status === 'verified') return t('console.channels.probeVerified')
  return probe.status === 'failed'
    ? t('console.channels.probeFailed')
    : t('console.channels.probeUnsupported')
}

async function restartChannel(ch: Channel): Promise<void> {
  await withAction(ch, 'restart', async () => {
    try {
      await rpc.call('channels.restart', { name: channelKey(ch) })
      pushToast(t('console.channels.toastRestarted', { name: channelKey(ch) }), { tone: 'ok' })
      await refresh()
    } catch (err) {
      pushToast(t('console.channels.toastRestartFailed', { name: channelKey(ch), error: errorMessage(err) }), { tone: 'danger' })
    }
  })
}

async function toggleChannel(ch: Channel): Promise<void> {
  await withAction(ch, 'toggle', async () => {
    const enabling = ch.enabled === false
    try {
      const res = await rpc.call<{ changed?: boolean; restartRequired?: boolean; liveApply?: Record<string, string> | null }>(`onboarding.channel.${enabling ? 'enable' : 'disable'}`, { name: channelKey(ch) })
      if (res?.changed !== false && res?.restartRequired !== false) pendingRestart.record(channelKey(ch), enabling ? 'enable' : 'disable')
      if (enabling && res?.liveApply?.[channelKey(ch)] === 'failed') {
        pushToast(t('setup.toast.channelStartFailed'), { tone: 'danger' })
      } else {
        pushToast(t(enabling ? 'console.channels.toastEnabled' : 'console.channels.toastDisabled', { name: channelKey(ch) }), { tone: 'ok' })
      }
      await refresh()
    } catch (err) {
      pushToast(t('console.channels.toastToggleFailed', { name: channelKey(ch), error: errorMessage(err) }), { tone: 'danger' })
    }
  })
}

async function loadConfiguration(ch: Channel): Promise<void> {
  configLoading.value = true
  configError.value = ''
  try {
    const result = await rpc.call<{ entry: Record<string, unknown>; secretFields?: string[] }>('channels.get', { name: channelKey(ch) })
    if (selectedName.value !== channelKey(ch)) return
    selectedConfig.value = result.entry
    selectedSecretFields.value = result.secretFields || []
  } catch (err) {
    configError.value = t('console.channels.configurationUnavailable', { error: errorMessage(err) })
  } finally { configLoading.value = false }
}

function errorMessage(err: unknown): string { return err instanceof Error ? err.message : String(err) }
function providerInitial(type?: string): string { return String(type || '?').slice(0, 1).toUpperCase() }
function pairingInitial(pairing: ChannelPairing): string { return String(pairing.senderName || pairing.senderId || '?').slice(0, 1).toUpperCase() }
// Curated per-type labels and a static transport, so a not-yet-loaded channel
// (no runtime capability_profile) still reads with the platform's real name
// and transport instead of a title-cased type slug.
const CURATED_LABELS: Record<string, string> = {
  slack: 'Slack', telegram: 'Telegram', discord: 'Discord', feishu: 'Feishu / Lark',
  dingtalk: 'DingTalk', wecom: 'WeCom', qq: 'QQ Bot', matrix: 'Matrix', msteams: 'Microsoft Teams',
}
const STATIC_TRANSPORT: Record<string, string> = {
  slack: 'Mixed', telegram: 'Polling', discord: 'WebSocket', feishu: 'Mixed',
  dingtalk: 'WebSocket', wecom: 'Mixed', qq: 'WebSocket', matrix: 'HTTP sync', msteams: 'Webhook',
}
function providerLabel(type?: string): string {
  const key = String(type || '').toLowerCase()
  return CURATED_LABELS[key] || humanize(type || t('console.channels.unknown'))
}
function humanize(value: string): string { return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, char => char.toUpperCase()) }
function transportLabel(ch: Channel): string {
  const live = (ch.capability_profile?.transports || []).map(humanize).join(' / ')
  if (live) return live
  return STATIC_TRANSPORT[String(ch.type || '').toLowerCase()] || t('console.channels.notReported')
}
function transportDescription(ch: Channel): string { return t('console.channels.transportDescription', { transport: transportLabel(ch) }) }

// Durable-delivery health derived from the journal, not hardcoded: an outbox
// with unknown-state entries needs operator review before a safe retry.
function deliveryReview(ch: Channel): { tone: string; label: string; detail: string } {
  const unknown = deliveryCount(ch, 'outbox', 'unknown')
  if (unknown > 0) {
    return {
      tone: 'warn',
      label: t('console.channels.needsReviewCount', { count: unknown }),
      detail: t('console.channels.durableReviewHint'),
    }
  }
  return { tone: 'ok', label: t('console.channels.active'), detail: t('console.channels.durableDescription') }
}

interface PlatformCapabilityRow { category: string; status?: string; notes?: string[] }
function platformRows(ch: Channel): Array<{ category: string; tone: string; label: string; notes: string }> {
  const caps = (ch.platform_manifest as { capabilities?: Record<string, PlatformCapabilityRow> } | null)?.capabilities
  if (!caps || typeof caps !== 'object') return []
  return Object.entries(caps).map(([category, row]) => {
    const status = String(row?.status || 'unsupported')
    const tone = status === 'supported' ? 'ok' : status === 'config_required' ? 'warn' : 'muted'
    const label = status === 'supported'
      ? t('console.channels.supported')
      : status === 'config_required'
        ? t('console.channels.needsConfig')
        : t('console.channels.notSupported')
    return { category, tone, label, notes: (row?.notes || []).join(' ') }
  })
}

function ownerSummary(ch: Channel): string {
  if (record(diagnostics(ch).transport_lease).fencing_token) return t('console.channels.ownerHere')
  const leases = delivery(ch).leases
  if (Array.isArray(leases) && leases.some(lease => !record(lease).expired)) return t('console.channels.ownerHere')
  return t('console.channels.ownerNone')
}

function maturityKey(ch: Channel): string {
  return String(ch.capability_profile?.maturity || 'unrated').replace(/^[A-Z]+-/, '').toLowerCase()
}

const MATURITY_KEYS = new Set(['experimental', 'stable', 'shipping', 'unrated'])
function maturityLabel(ch: Channel): string {
  const key = maturityKey(ch)
  return MATURITY_KEYS.has(key) ? t(`console.channels.maturityValue.${key}`) : humanize(key)
}


function formatSince(since?: string | number | null): string {
  if (!since) return '—'
  const date = new Date(since)
  return Number.isNaN(date.getTime()) ? String(since) : date.toLocaleString()
}

function capabilityRows(ch: Channel): Array<CapabilityEvidence & { name: string }> {
  const evidence = ch.capability_profile?.evidence || {}
  return Object.entries(evidence).map(([name, value]) => ({ name, ...value })).sort((a, b) => Number(Boolean(b.effective)) - Number(Boolean(a.effective)) || a.name.localeCompare(b.name))
}

function evidenceLabel(capability: CapabilityEvidence): string {
  if (capability.methods?.length) return t('console.channels.methodEvidence', { methods: capability.methods.join(', ') })
  return capability.proof_status === 'verified' ? t('console.channels.liveVerified') : t('console.channels.declarationEvidence')
}

function diagnostics(ch: Channel): Record<string, unknown> { return ch.diagnostics && typeof ch.diagnostics === 'object' ? ch.diagnostics : {} }
function delivery(ch: Channel): Record<string, unknown> { const value = diagnostics(ch).delivery; return value && typeof value === 'object' ? value as Record<string, unknown> : {} }
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' ? value as Record<string, unknown> : {} }

function deliveryCount(ch: Channel, section: string, state: string): number {
  return Number(record(record(delivery(ch)[section])[state]).count || 0)
}

function lastError(ch: Channel): string {
  const value = diagnostics(ch).last_error
  if (!value || typeof value !== 'object') return ''
  return String(record(value).message || record(value).error_class || '')
}


function probeResultDetail(ch: Channel): string {
  const result = probeResults.value[channelKey(ch)]
  if (!result) return ''
  if (result.detail) return result.detail
  if (result.latencyMs != null) return t('console.channels.probeLatency', { ms: result.latencyMs })
  return t('console.channels.probeNoDetail')
}

function configRows(config: Record<string, unknown>): Array<{ key: string; value: string; secret: boolean }> {
  return Object.entries(config).filter(([key]) => !['name', 'type'].includes(key)).map(([key, value]) => {
    const secret = value === SECRET_MARKER || selectedSecretFields.value.includes(key)
    const display = secret ? t('console.channels.secretStored') : Array.isArray(value) ? value.join(', ') || '—' : String(value ?? '—')
    return { key, value: display, secret }
  })
}
</script>

<style scoped>
.ch-sr-only { height: 1px; margin: -1px; overflow: hidden; padding: 0; position: absolute; width: 1px; clip: rect(0, 0, 0, 0); white-space: nowrap; }
.ch-summary { align-items: stretch; display: flex; flex-wrap: wrap; width: fit-content; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-control); overflow: hidden; }
.ch-summary__item { align-items: center; background: transparent; border: 0; border-right: 1px solid var(--border); color: var(--text-muted); cursor: pointer; display: flex; font: inherit; gap: 7px; min-height: 38px; padding: 7px 14px; }
.ch-summary__item:last-child { border-right: 0; }
.ch-summary__item:hover, .ch-summary__item.is-active { background: var(--bg-surface-2); color: var(--text); }
.ch-summary__item.is-active { box-shadow: inset 0 -2px var(--accent); }
.ch-summary__item strong { color: var(--text); font-variant-numeric: tabular-nums; }
.dot { background: var(--text-dim); border-radius: 50%; display: inline-block; height: 8px; width: 8px; }
.ch-summary__item.tone-ok .dot { background: var(--ok); }
.ch-summary__item.tone-info .dot { background: var(--info); }
.ch-summary__item.tone-danger .dot { background: var(--danger); }
.ch-summary__item.tone-muted .dot { background: var(--text-dim); }
.ch-context { color: var(--text-dim); font-size: var(--fs-sm); margin: 0; }
.ch-context a { color: var(--accent); }
.ch-query-missing { align-items: center; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-muted); display: flex; flex-wrap: wrap; font-size: var(--fs-sm); gap: var(--sp-2); grid-column: 1 / -1; justify-content: space-between; margin: 0; padding: 8px 12px; }
.ch-query-missing > span { min-width: 0; overflow-wrap: anywhere; }
.ch-detail__remove { color: var(--danger); }
.ch-toolbar { align-items: center; display: flex; flex-wrap: wrap; gap: var(--sp-3); }
.ch-search { align-items: center; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-control); color: var(--text-dim); display: flex; gap: 8px; min-width: min(320px, 100%); padding: 0 11px; }
.ch-search:focus-within, .ch-select:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
.ch-search input, .ch-select select { background: transparent; border: 0; color: var(--text); font: inherit; min-height: 36px; outline: 0; width: 100%; }
.ch-select { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-control); min-width: 180px; padding: 0 8px; }
.ch-toolbar__result { color: var(--text-dim); font-size: var(--fs-sm); }
.ch-workspace { display: grid; gap: var(--sp-4); grid-template-columns: minmax(0, 1fr); min-height: 480px; }
.ch-workspace.has-detail { grid-template-columns: minmax(460px, 1fr) minmax(420px, 46%); }
.ch-table-wrap { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); min-width: 0; overflow: auto; }
.ch-table { border-collapse: collapse; font-size: var(--fs-sm); min-width: 700px; width: 100%; }
.ch-workspace.has-detail .ch-table { min-width: 560px; }
.ch-table th { color: var(--text-dim); font-size: 11px; font-weight: 600; letter-spacing: .04em; padding: 12px 14px; text-align: left; text-transform: uppercase; }
.ch-table td { border-top: 1px solid var(--border); color: var(--text); padding: 14px; vertical-align: middle; }
.ch-table tbody tr { cursor: pointer; outline: 0; }
.ch-table tbody tr:hover, .ch-table tbody tr:focus-visible, .ch-table tbody tr.is-selected { background: var(--bg-surface-2); }
.ch-table tbody tr.is-selected { box-shadow: inset 3px 0 var(--accent); }
.ch-table td:first-child { align-items: center; display: flex; gap: 9px; }
.ch-table td:last-child { color: var(--text-dim); text-align: right; }
.ch-table__none { color: var(--text-dim) !important; padding: 36px !important; text-align: center !important; }
.ch-provider-mark { align-items: center; background: color-mix(in srgb, var(--accent) 16%, var(--bg-surface-2)); border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border)); border-radius: var(--radius-sm); color: var(--accent); display: inline-flex; flex: 0 0 auto; font-weight: 800; height: 28px; justify-content: center; width: 28px; }
.ch-provider-mark.is-large { border-radius: var(--radius-md); font-size: 18px; height: 42px; width: 42px; }
.ch-muted { color: var(--text-dim); }
.ch-mono { font-family: var(--font-mono); font-size: 11px; }
.ch-maturity, .ch-proof { border: 1px solid var(--border); border-radius: var(--radius-full); color: var(--text-muted); display: inline-flex; font-size: 10px; font-weight: 700; letter-spacing: .03em; padding: 3px 8px; text-transform: uppercase; white-space: nowrap; }
.ch-maturity.is-stable, .ch-proof.is-effective { border-color: color-mix(in srgb, var(--ok) 45%, var(--border)); color: var(--ok); }
.ch-maturity.is-experimental { border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); color: var(--warn); }
.ch-proof.is-config { border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); color: var(--warn); }
.ch-inline-link { background: transparent; border: 0; color: var(--accent); cursor: pointer; font: inherit; font-size: 11px; padding: 0; }
.ch-inline-link:hover { text-decoration: underline; }
.ch-check-row.is-warn-row > svg { color: var(--warn); }
.ch-capability > svg.is-ok { color: var(--ok); }
.ch-capability > svg.is-warn { color: var(--warn); }
.ch-capability > svg.is-muted { color: var(--text-dim); }
.ch-tech { border: 1px solid var(--border); border-radius: var(--radius-md); margin-top: var(--sp-3); padding: 0 var(--sp-2); }
.ch-tech > summary { color: var(--text-muted); cursor: pointer; font-size: var(--fs-sm); padding: 10px 6px; }
.ch-detail { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); display: flex; flex-direction: column; min-height: 620px; min-width: 0; overflow: hidden; }
.ch-detail__header { align-items: flex-start; display: flex; gap: var(--sp-3); justify-content: space-between; padding: var(--sp-4); }
.ch-detail__identity { align-items: center; display: flex; gap: var(--sp-3); min-width: 0; }
.ch-detail__identity > div { min-width: 0; }
.ch-detail__title-row { align-items: center; display: flex; flex-wrap: wrap; gap: 10px; }
.ch-detail__title-row h2 { font-size: var(--fs-lg); margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-detail__identity p { color: var(--text-dim); font-size: var(--fs-sm); margin: 4px 0 0; }
.ch-icon-btn { align-items: center; background: transparent; border: 0; border-radius: var(--radius-sm); color: var(--text-muted); cursor: pointer; display: inline-flex; justify-content: center; padding: 6px; }
.ch-icon-btn:hover { background: var(--bg-surface-2); color: var(--text); }
.ch-detail__actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 var(--sp-4) var(--sp-3); }
.ch-detail__actions .btn { min-height: 32px; padding: 5px 10px; }
.ch-detail__actiongroup { display: flex; flex-wrap: wrap; gap: 8px; }
.ch-detail__actionsep { align-self: stretch; background: var(--border); flex: 0 0 1px; margin: 3px 2px; width: 1px; }
.ch-detail__actions .ch-detail__remove { margin-left: auto; }
.ch-detail__tabs { border-bottom: 1px solid var(--border); border-top: 1px solid var(--border); display: flex; overflow-x: auto; padding: 0 var(--sp-4); }
.ch-detail__tabs button { background: transparent; border: 0; color: var(--text-muted); cursor: pointer; font: inherit; font-size: var(--fs-sm); font-weight: 600; padding: 12px 13px; position: relative; white-space: nowrap; }
.ch-detail__tabs button:hover, .ch-detail__tabs button.is-active { color: var(--text); }
.ch-detail__tabs button.is-active::after { background: var(--accent); bottom: 0; content: ''; height: 2px; left: 10px; position: absolute; right: 10px; }
.ch-row-badge { cursor: pointer; margin-left: 8px; }
.ch-summary__item.tone-warn .dot { background: var(--warn); }
.ch-tab-badge { background: color-mix(in srgb, var(--warn) 20%, transparent); border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--border)); border-radius: var(--radius-full); color: var(--warn); font-size: 10px; font-weight: 700; margin-left: 6px; padding: 0 6px; }
.ch-detail__body { display: grid; gap: var(--sp-3); overflow-y: auto; padding: var(--sp-4); }
.ch-panel, .ch-alert { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.ch-panel > h3, .ch-panel__heading { align-items: center; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; margin: 0; padding: 12px 14px; }
.ch-panel h3 { font-size: var(--fs-sm); margin: 0; }
.ch-panel__intro { color: var(--text-dim); font-size: var(--fs-sm); line-height: 1.5; margin: 0; padding: 12px 14px 0; }
.ch-check-row { align-items: center; border-top: 1px solid var(--border); display: grid; gap: 11px; grid-template-columns: 20px minmax(0, 1fr) auto; padding: 13px 14px; }
.ch-panel > h3 + .ch-check-row { border-top: 0; }
.ch-check-row > svg { color: var(--text-muted); }
.ch-check-row div { display: grid; gap: 3px; }
.ch-check-row strong { font-size: var(--fs-sm); }
.ch-check-row span { color: var(--text-dim); font-size: 11px; }
.ch-check-row b { font-size: 11px; }
.is-ok { color: var(--ok); }
.is-muted { color: var(--text-dim); }
.is-warn { color: var(--warn); }
.ch-facts dl, .ch-config-list { margin: 0; }
.ch-facts dl > div, .ch-config-list > div { align-items: baseline; border-top: 1px solid var(--border); display: flex; gap: var(--sp-3); justify-content: space-between; padding: 11px 14px; }
.ch-facts dl > div:first-child, .ch-config-list > div:first-child { border-top: 0; }
.ch-facts dt, .ch-config-list dt { color: var(--text-dim); font-size: var(--fs-sm); }
.ch-facts dd, .ch-config-list dd { font-family: var(--font-mono); font-size: 11px; margin: 0; max-width: 64%; overflow-wrap: anywhere; text-align: right; }
.ch-config-list dd.is-secret { color: var(--ok); font-family: var(--font-sans); }
.ch-probe-result, .ch-alert { align-items: flex-start; display: flex; gap: 10px; padding: 12px 14px; }
.ch-probe-result { background: color-mix(in srgb, var(--ok) 8%, var(--bg)); border: 1px solid color-mix(in srgb, var(--ok) 36%, var(--border)); border-radius: var(--radius-md); color: var(--ok); }
.ch-probe-result.is-danger { background: color-mix(in srgb, var(--danger) 8%, var(--bg)); border-color: color-mix(in srgb, var(--danger) 36%, var(--border)); color: var(--danger); }
.ch-probe-result.is-muted { background: var(--bg); border-color: var(--border); color: var(--text-muted); }
.ch-probe-result__edit { margin-top: 8px; min-height: 28px; padding: 3px 9px; }
.ch-probe-result p, .ch-alert p { color: var(--text-muted); font-size: var(--fs-sm); margin: 3px 0 0; }
.ch-probe-result > div, .ch-alert > div { min-width: 0; overflow-wrap: anywhere; }
.ch-alert.is-danger { background: color-mix(in srgb, var(--danger) 8%, var(--bg)); border-color: color-mix(in srgb, var(--danger) 38%, var(--border)); color: var(--danger); }
.ch-alert-text { color: var(--danger); font-size: var(--fs-sm); padding: 12px 14px; }
.ch-capabilities { padding: 8px 0; }
.ch-capability { align-items: center; display: grid; gap: 10px; grid-template-columns: 18px minmax(0, 1fr) auto; padding: 9px 14px; }
.ch-capability > svg { color: var(--ok); }
.ch-capability div { display: grid; gap: 2px; }
.ch-capability strong { font-size: var(--fs-sm); }
.ch-capability span:not(.ch-proof) { color: var(--text-dim); font-size: 11px; }
.ch-proof.is-declared { color: var(--text-dim); }
.ch-pairings .ch-panel__heading { align-items: flex-start; gap: var(--sp-3); }
.ch-pairings .ch-panel__heading > div { min-width: 0; }
.ch-pairings .ch-panel__heading p { color: var(--text-dim); font-size: 11px; line-height: 1.45; margin: 4px 0 0; }
.ch-pairing-summary { align-items: center; border-bottom: 1px solid var(--border); color: var(--text-muted); display: flex; flex-wrap: wrap; font-size: 11px; gap: 6px var(--sp-4); padding: 9px 14px; }
.ch-pairing-summary strong { color: var(--text); font-family: var(--font-mono); }
.ch-pairing-state { align-items: center; color: var(--text-dim); display: flex; flex-direction: column; gap: 8px; justify-content: center; min-height: 180px; padding: var(--sp-4); text-align: center; }
.ch-pairing-state.is-error { color: var(--danger); }
.ch-pairing-groups > section + section { border-top: 1px solid var(--border); }
.ch-pairing-groups h4 { color: var(--text-dim); font-size: 11px; letter-spacing: .04em; margin: 0; padding: 11px 14px 7px; text-transform: uppercase; }
.ch-pairing-row { align-items: center; display: grid; gap: 10px; grid-template-columns: 32px minmax(0, 1fr) auto auto; padding: 10px 14px; }
.ch-pairing-row + .ch-pairing-row { border-top: 1px solid var(--border); }
.ch-pairing-avatar { align-items: center; background: var(--bg-surface-2); border: 1px solid var(--border); border-radius: 50%; color: var(--text-muted); display: flex; font-size: 12px; font-weight: 800; height: 32px; justify-content: center; width: 32px; }
.ch-pairing-identity { display: grid; gap: 2px; min-width: 0; }
.ch-pairing-identity strong, .ch-pairing-identity span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-pairing-identity strong { font-size: var(--fs-sm); }
.ch-pairing-identity .ch-pairing-code { color: var(--warn); font-size: 10px; }
.ch-pairing-identity time { color: var(--text-dim); font-size: 10px; }
.ch-pairing-status { border: 1px solid var(--border); border-radius: var(--radius-full); font-size: 10px; font-weight: 700; padding: 3px 8px; text-transform: uppercase; }
.ch-pairing-status.is-pending { border-color: color-mix(in srgb, var(--warn) 42%, var(--border)); color: var(--warn); }
.ch-pairing-status.is-approved { border-color: color-mix(in srgb, var(--ok) 42%, var(--border)); color: var(--ok); }
.ch-pairing-status.is-revoked { border-color: color-mix(in srgb, var(--danger) 42%, var(--border)); color: var(--danger); }
.ch-pairing-search { align-items: center; border-bottom: 1px solid var(--border); color: var(--text-dim); display: flex; gap: 8px; padding: 8px 14px; }
.ch-pairing-search input { background: transparent; border: 0; color: var(--text); font: inherit; outline: 0; width: 100%; }
.ch-pairing-revoke { color: var(--danger); }
.ch-metrics { display: grid; grid-template-columns: repeat(2, 1fr); }
.ch-metrics > div { border-right: 1px solid var(--border); border-top: 1px solid var(--border); display: grid; gap: 4px; padding: 14px; }
.ch-metrics > div:nth-child(even) { border-right: 0; }
.ch-metrics strong { font-family: var(--font-mono); font-size: var(--fs-lg); }
.ch-metrics span { color: var(--text-dim); font-size: 11px; }
.ch-metrics > div.is-warn strong { color: var(--warn); }
.ch-empty { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); gap: var(--sp-3); }
.ch-stale { align-items: center; background: color-mix(in srgb, var(--warn) 8%, var(--bg-surface)); border: 1px solid color-mix(in srgb, var(--warn) 38%, var(--border)); border-radius: var(--radius-md); color: var(--text-muted); display: flex; font-size: var(--fs-sm); gap: var(--sp-2); margin: 0; padding: 7px 12px; }
.ch-stale > svg { color: var(--warn); flex: 0 0 auto; }
.ch-stale > span { flex: 1; }
.ch-table__none { display: flex !important; flex-direction: column; gap: 8px; align-items: center; }
.is-spinning { animation: ch-spin 0.9s linear infinite; }
@keyframes ch-spin { to { transform: rotate(360deg); } }
.ch-scrim { display: none; }
.ch-unconfigured { border-top: 1px solid var(--border); padding: var(--sp-3) var(--sp-4); }
.ch-unconfigured h4 { color: var(--text); font-size: var(--fs-sm); margin: 0 0 2px; }
.ch-unconfigured p { color: var(--text-dim); font-size: 11px; margin: 0 0 var(--sp-2); }
.ch-unconfigured__row { align-items: center; display: flex; gap: 9px; padding: 6px 0; }
.ch-unconfigured__row strong { font-size: var(--fs-sm); }
.ch-empty__icon { align-items: center; background: color-mix(in srgb, var(--accent) 12%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--border)); border-radius: 50%; color: var(--accent); display: flex; height: 72px; justify-content: center; width: 72px; }

@media (max-width: 1180px) {
  .ch-workspace.has-detail { grid-template-columns: minmax(0, 1fr); }
  /* min-height:0 resets the desktop split-pane floor so the fixed overlay
     never extends past the viewport on short/landscape screens. */
  .ch-detail { bottom: 12px; box-shadow: var(--elev-3); max-width: 560px; min-height: 0; position: fixed; right: 12px; top: 64px; width: calc(100vw - 24px); z-index: 40; }
  .ch-detail__body { overscroll-behavior: contain; }
  .ch-scrim { background: color-mix(in srgb, var(--bg) 60%, transparent); display: block; inset: 0; overscroll-behavior: contain; position: fixed; z-index: 39; }
}
/* 768px matches the app's mobile breakpoint (the bottom tab bar appears
   there); using 760px left an 8px window where the overlay sat under it. */
@media (max-width: 768px) {
  .ch-stage__header { align-items: stretch; flex-direction: column; }
  .ch-stage__actions { justify-content: stretch; }
  .ch-stage__actions .btn { flex: 1; }
  .ch-summary { display: flex; width: 100%; }
  .ch-summary__item { border-bottom: 1px solid var(--border); flex: 1 1 auto; justify-content: center; }
  .ch-search, .ch-select { min-width: 100%; }
  .ch-provider-name { display: none; }
  /* Status must stay visible on a phone; transport and connected-since are
     the sacrificial columns. */
  .ch-table { min-width: 0; }
  .ch-hide-mobile { display: none; }
  /* The fixed overlay ends above the mobile tab bar (z-60, 56px + safe area)
     so the last rows are never permanently covered. max-width/right reset
     the stale 1180px-block geometry. */
  .ch-detail {
    border-radius: var(--radius-md);
    bottom: calc(var(--mobile-tabbar-h, 56px) + env(safe-area-inset-bottom, 0px));
    left: 0;
    max-width: none;
    right: 0;
    top: 48px;
    width: auto;
  }
  .ch-detail__body { padding: var(--sp-3); }
  /* Wrapped action rows: the divider loses meaning and the auto-margin
     strands Remove on its own line edge. */
  .ch-detail__actionsep { display: none; }
  .ch-detail__actions .ch-detail__remove { margin-left: 0; }
  /* Touch-target floor for the compact text controls this view introduces. */
  .ch-inline-link { align-items: center; display: inline-flex; min-height: 44px; }
  .ch-icon-btn { min-height: 40px; min-width: 40px; }
  .ch-summary__item { min-height: 44px; }
  .ch-check-row { grid-template-columns: 20px minmax(0, 1fr); }
  .ch-check-row > b, .ch-check-row > .ch-inline-link { grid-column: 2; justify-self: start; white-space: nowrap; }
  .ch-capability { grid-template-columns: 18px minmax(0, 1fr); }
  .ch-proof { grid-column: 2; width: fit-content; }
  .ch-pairing-row { grid-template-columns: 32px minmax(0, 1fr) auto; }
  .ch-pairing-row .btn { grid-column: 2 / -1; justify-self: start; }
}
</style>
