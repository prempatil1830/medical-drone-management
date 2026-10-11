import { create } from 'zustand';

const STORAGE_KEY = 'aeromedical_delivered_ids';

const loadDeliveredIds = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
};

export const useDeliveryStore = create((set, get) => ({
  deliveredIds: loadDeliveredIds(),

  markDelivered: (...ids) => {
    const validIds = ids.filter(Boolean).map(String);
    if (!validIds.length) return;

    const current = get().deliveredIds;
    const merged = Array.from(new Set([...current, ...validIds]));

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
    } catch (e) {
      console.error('Failed to save delivered status:', e);
    }

    set({ deliveredIds: merged });
  },

  isDelivered: (id) => {
    if (!id) return false;
    return get().deliveredIds.includes(String(id));
  },

  applyOverrides: (items) => {
    if (!Array.isArray(items)) return items;
    const ids = get().deliveredIds;
    return items.map((item) => {
      const match =
        ids.includes(String(item.id)) ||
        ids.includes(String(item.request_id)) ||
        ids.includes(String(item.mission_id));
      if (match) {
        return {
          ...item,
          status: 'DELIVERED',
        };
      }
      return item;
    });
  },
}));
