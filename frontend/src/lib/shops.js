export function normalizeShopImages(images) {
  if (Array.isArray(images)) {
    return images.map((item) => String(item || '').trim()).filter(Boolean);
  }

  return String(images || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatShopMeta(shop) {
  const parts = [];

  if (shop?.area) {
    parts.push(shop.area);
  }

  if (shop?.avgPrice != null && shop.avgPrice !== '') {
    parts.push(`人均 ¥${shop.avgPrice}`);
  }

  if (shop?.openHours) {
    parts.push(shop.openHours);
  }

  return parts.join(' · ');
}

export function formatScore(score) {
  const numeric = Number(score);
  if (!Number.isFinite(numeric)) {
    return '0.0';
  }

  const normalized = numeric > 10 ? numeric / 10 : numeric;
  return normalized.toFixed(1);
}

export function formatDistance(distance) {
  const numeric = Number(distance);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return '';
  }

  if (numeric >= 1) {
    return `${numeric.toFixed(1)}km`;
  }

  return `${Math.round(numeric * 1000)}m`;
}

export function formatPrice(value) {
  if (value == null || value === '') {
    return '待补充';
  }

  return `¥${value}`;
}

export function pickShopCover(shop) {
  const images = normalizeShopImages(shop?.images);
  return images[0] || '';
}

export function buildShopTags(shop, typeName) {
  const tags = [];
  if (typeName) tags.push(typeName);
  if (shop?.area) tags.push(shop.area);
  if (shop?.sold != null) tags.push(`月售 ${shop.sold}`);
  if (shop?.distance != null) {
    const distance = formatDistance(shop.distance);
    if (distance) tags.push(distance);
  }
  return tags.slice(0, 4);
}
