const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('public/js/messages.js', 'utf8');
const list = {
  scrollTop: 0,
  scrollHeight: 1000,
  clientHeight: 200,
  set innerHTML(value) {
    this.html = value;
    this.scrollHeight = 1200;
  },
};
const context = {
  messageEls: { messageList: list },
  messageState: { messages: [{ id: 1 }] },
  renderMessage: message => String(message.id),
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function renderMessages('), source.indexOf('async function loadMessages(')), context);

list.scrollTop = 0;
context.renderMessages();
assert.equal(list.scrollTop, 0, 'refresh must preserve a reader at the top');

list.scrollHeight = 1000;
list.scrollTop = 800;
context.renderMessages();
assert.equal(list.scrollTop, 1200, 'refresh should follow new messages when already at the bottom');

list.scrollHeight = 1000;
list.scrollTop = 300;
context.renderMessages({ scrollToBottom: true });
assert.equal(list.scrollTop, 1200, 'sending or opening a conversation should show the newest message');
