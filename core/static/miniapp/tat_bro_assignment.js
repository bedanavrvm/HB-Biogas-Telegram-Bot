(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TatBroAssignment = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function clean(value) {
    return String(value == null ? '' : value).trim();
  }

  function normalizeUsers(users, fallbackNames) {
    const source = Array.isArray(users) && users.length
      ? users
      : (fallbackNames || []).map((name) => ({ name }));
    return source.map((user, index) => {
      const id = clean(user && user.id);
      const username = clean(user && user.username);
      const telegramUsername = clean(user && user.telegram_username).replace(/^@/, '');
      const name = clean(user && user.name) || username || telegramUsername || 'Unnamed BRO';
      return {
        id,
        name,
        username,
        telegram_username: telegramUsername,
        option_value: id || `legacy:${index}`,
      };
    });
  }

  function optionRows(users) {
    const counts = new Map();
    users.forEach((user) => {
      const key = user.name.toLocaleLowerCase();
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return users.map((user) => {
      let label = user.name;
      if ((counts.get(user.name.toLocaleLowerCase()) || 0) > 1) {
        const identity = user.telegram_username
          ? `@${user.telegram_username}`
          : user.username || `user ${user.id || 'unknown'}`;
        label = `${user.name} (${identity})`;
      }
      return { value: user.option_value, label };
    });
  }

  function defaultValue(users, defaultUserId) {
    const requested = clean(defaultUserId);
    const selected = requested && users.find((user) => user.id === requested);
    return selected ? selected.option_value : '';
  }

  function selectionPayload(users, selectedValue) {
    const value = clean(selectedValue);
    const selected = users.find((user) => user.option_value === value);
    if (!selected) return { bro_user_id: '', bro_name: '' };
    return {
      bro_user_id: selected.id,
      bro_name: selected.name,
    };
  }

  function populateSelect(select, users, defaultUserId) {
    if (!select) return;
    select.innerHTML = '';
    const rows = [{ value: '', label: 'Select BRO' }].concat(optionRows(users));
    rows.forEach((row) => {
      const option = select.ownerDocument.createElement('option');
      option.value = row.value;
      option.textContent = row.label;
      select.appendChild(option);
    });
    select.value = defaultValue(users, defaultUserId);
  }

  return {
    defaultValue,
    normalizeUsers,
    optionRows,
    populateSelect,
    selectionPayload,
  };
});
