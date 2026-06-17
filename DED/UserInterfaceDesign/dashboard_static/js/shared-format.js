export function createChartViewState() {
    return {
        startRatio: 0,
        endRatio: 1,
        pointerId: null,
        dragStartX: 0,
        dragStartStart: 0,
        dragStartEnd: 1,
        dragMoved: false,
    };
}

export function formatNumber(value, digits = 3) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "-";
    }
    return Number(value).toFixed(digits);
}

export function formatInteger(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "-";
    }
    return `${Math.round(Number(value))}`;
}

export function formatSignedMilliseconds(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "-";
    }
    const rounded = Math.round(Number(value));
    const prefix = rounded > 0 ? "+" : "";
    return `${prefix}${rounded} ms`;
}

export function isRelativeTimestamp(timestampMs) {
    return Number.isFinite(Number(timestampMs)) && Math.abs(Number(timestampMs)) < 100000000000;
}

export function formatRelativeTimestamp(timestampMs) {
    const rounded = Math.round(Number(timestampMs));
    const sign = rounded < 0 ? "-" : "";
    return `T${sign}+${Math.abs(rounded)} ms`;
}

export function formatChartTime(timestampMs) {
    if (isRelativeTimestamp(timestampMs)) {
        return formatRelativeTimestamp(timestampMs);
    }
    const date = new Date(Number(timestampMs));
    if (Number.isNaN(date.getTime())) {
        return "-";
    }
    const pad = (value, size = 2) => String(value).padStart(size, "0");
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

export function formatFullTimestamp(timestampMs) {
    if (isRelativeTimestamp(timestampMs)) {
        return formatRelativeTimestamp(timestampMs);
    }
    const date = new Date(Number(timestampMs));
    if (Number.isNaN(date.getTime())) {
        return "-";
    }
    const pad = (value, size = 2) => String(value).padStart(size, "0");
    return [
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
        `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`,
    ].join(" ");
}

export function clamp(value, min, max) {
    return Math.min(Math.max(Number(value), min), max);
}

export function clampIndex(value, maxIndex) {
    return Math.min(Math.max(Number(value) || 0, 0), Math.max(Number(maxIndex) || 0, 0));
}
