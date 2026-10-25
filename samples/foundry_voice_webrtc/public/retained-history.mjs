const transcriptEvent = /^response\.(output_audio_transcript|audio_transcript|output_text|text)\.(delta|done)$/;

function itemParts(item) {
  if (item?.type !== 'message' || item.role !== 'assistant' || !Array.isArray(item.content))
    throw new Error('Azure returned an invalid retained assistant item.');
  return item.content.map(part => typeof part.text === 'string' ? part.text :
    typeof part.transcript === 'string' ? part.transcript : '');
}

export class RetainedHistory {
  constructor({render, remove, retrieve, error, timers = globalThis}) {
    Object.assign(this, {render, remove, retrieve, error, timers});
    this.items = new Map();
    this.responses = new Map();
    this.clearedResponses = new Set();
    this.retrievalIds = new Set();
  }
  item(id, role = 'assistant') {
    if (!this.items.has(id))
      this.items.set(id, {id, role, text:'', parts:new Map(), cuts:new Map(), version:0, status:'live'});
    return this.items.get(id);
  }
  show(record) {
    // ID-less drafts wait for output_item metadata; a response can contain multiple items.
    if (!record.hidden && !record.id.startsWith('response:')) this.render(record);
  }
  user(id, text) {
    if (!id || typeof text !== 'string') return;
    const record = this.item(id, 'user');
    record.text = text;
    record.status = 'complete';
    this.show(record);
  }
  resolve(event, itemId = event.item_id) {
    const responseId = event.response_id;
    const index = event.output_index ?? 0;
    let outputs = this.responses.get(responseId);
    if (responseId && !outputs) this.responses.set(responseId, outputs = new Map());
    const previous = outputs?.get(index);
    let record = itemId ? this.items.get(itemId) : previous;
    if (itemId && previous && previous.id.startsWith('response:')) {
      this.items.delete(previous.id);
      if (record && record !== previous) {
        record.hidden ||= previous.hidden;
        this.remove(previous);
      } else {
        record = previous;
        record.id = itemId;
        this.items.set(itemId, record);
      }
    }
    if (!record) {
      if (!itemId && !responseId) throw new Error('Azure returned assistant text without an item or response ID.');
      record = this.item(itemId || `response:${responseId}:${index}`);
    }
    if (outputs) outputs.set(index, record);
    if (this.clearedResponses.has(responseId)) record.hidden = true;
    if (record.hidden) this.remove(record);
    return record;
  }
  applyItem(event, item) {
    if (item?.type !== 'message' || item.role !== 'assistant' || !item.id) return;
    const record = this.resolve(event, item.id);
    if (record.version) return;
    const parts = itemParts(item);
    record.text = parts.join('\n');
    record.parts = new Map(parts.map((text, index) => [index, text]));
    record.status = event.type.endsWith('.done') ? 'complete' : 'live';
    this.show(record);
  }
  retained(record, item) {
    if (item?.id !== record.id) throw new Error('Azure returned a retained item with the wrong item ID.');
    record.text = itemParts(item).join('\n');
    record.parts.clear();
    record.status = 'truncated';
    this.show(record);
  }
  request(record) {
    if (record.retrievalBlocked) {
      this.unavailable(record, 'A previous retrieval timed out. Restart to retry, or wait for an enriched truncation event.');
      return;
    }
    // One in-flight retrieval per item: replies carry item.id, not the request event_id.
    if (record.request) return;
    const request = record.request = {id:crypto.randomUUID().replaceAll('-', ''), version:record.version};
    this.retrievalIds.add(request.id);
    request.timeout = this.timers.setTimeout(() => {
      record.retrievalBlocked = true;
      this.unavailable(record, 'Retrieval timed out.');
    }, 10000);
    try { this.retrieve(record.id, request.id); }
    catch (error) { this.unavailable(record, error.message); }
  }
  unavailable(record, reason) {
    if (record.request) this.timers.clearTimeout(record.request.timeout);
    record.request = null;
    if (record.status !== 'pending') return;
    record.status = 'unavailable';
    record.text = '';
    this.show(record);
    if (!record.hidden) this.error(`Retained history unavailable for ${record.id}: ${reason}`);
  }
  truncate(event) {
    if (!event.item_id || !Number.isInteger(event.content_index) || event.content_index < 0 ||
        !Number.isFinite(event.audio_end_ms) || event.audio_end_ms < 0)
      throw new Error('Azure returned invalid truncation coordinates.');
    const record = this.item(event.item_id);
    const previous = record.cuts.get(event.content_index);
    if (previous !== undefined && event.audio_end_ms > previous) return;
    if (previous === event.audio_end_ms && (record.status === 'truncated' || !event.item)) return;
    record.cuts.set(event.content_index, event.audio_end_ms);
    record.version++;
    record.parts.clear();
    record.text = '';
    record.status = 'pending';
    this.show(record);
    if (event.item) {
      try { this.retained(record, event.item); }
      catch (error) { this.unavailable(record, error.message); }
    } else this.request(record);
  }
  retrieved(event) {
    const record = this.items.get(event.item?.id || event.item_id);
    if (!record?.request) return;
    const request = record.request;
    this.timers.clearTimeout(request.timeout);
    record.request = null;
    if (record.status !== 'pending') return;
    if (request.version !== record.version) {
      this.request(record);
      return;
    }
    try { this.retained(record, event.item); }
    catch (error) { this.unavailable(record, error.message); }
  }
  handle(event) {
    if (event.type === 'response.created') {
      if (event.response?.id && !this.responses.has(event.response.id)) this.responses.set(event.response.id, new Map());
    } else if (event.type === 'conversation.item.truncated') this.truncate(event);
    else if (event.type === 'conversation.item.retrieved') this.retrieved(event);
    else if (event.type === 'error') {
      for (const record of this.items.values()) {
        if (record.request && record.request.id === event.error?.event_id) {
          this.unavailable(record, event.error.message || 'Azure rejected item retrieval.');
          return true;
        }
      }
      return this.retrievalIds.has(event.error?.event_id);
    } else if (transcriptEvent.test(event.type)) {
      const record = this.resolve(event);
      if (record.version) return true;
      const index = event.content_index ?? 0;
      const text = event.delta ?? event.transcript ?? event.text;
      if (typeof text !== 'string') return true;
      record.parts.set(index, event.type.endsWith('.delta') ? (record.parts.get(index) || '') + text : text);
      record.text = [...record.parts].sort(([a], [b]) => a - b).map(([, value]) => value).join('\n');
      record.status = event.type.endsWith('.done') ? 'complete' : 'live';
      this.show(record);
    } else if (['response.output_item.added', 'response.output_item.done', 'conversation.item.created',
                'conversation.item.added', 'conversation.item.done'].includes(event.type)) {
      this.applyItem(event, event.item);
    } else if (event.type === 'response.done') {
      event.response?.output?.forEach((item, index) =>
        this.applyItem({...event, response_id:event.response.id, output_index:index}, item));
    } else return false;
    return true;
  }
  clear() {
    // Keep item/response tombstones so late events cannot resurrect cleared history.
    for (const record of this.items.values()) record.hidden = true;
    for (const id of this.responses.keys()) this.clearedResponses.add(id);
  }
  dispose() {
    for (const record of this.items.values()) this.unavailable(record, 'The session ended before retrieval completed.');
  }
}
