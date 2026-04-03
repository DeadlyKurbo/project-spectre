const DEG_TO_RAD = Math.PI / 180;
const RAD_TO_DEG = 180 / Math.PI;

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function normalizeLongitude(lonDeg) {
    let lon = Number(lonDeg) || 0;
    while (lon > 180) lon -= 360;
    while (lon < -180) lon += 360;
    return lon;
}

function latLonToVector3(latDeg, lonDeg, radius = 100) {
    const lat = clamp(Number(latDeg) || 0, -89.999, 89.999) * DEG_TO_RAD;
    const lon = normalizeLongitude(lonDeg) * DEG_TO_RAD;
    const cosLat = Math.cos(lat);
    const x = radius * cosLat * Math.cos(lon);
    const y = radius * Math.sin(lat);
    const z = -radius * cosLat * Math.sin(lon);
    return { x, y, z };
}

function vector3ToLatLon(x, y, z) {
    const r = Math.sqrt((x * x) + (y * y) + (z * z)) || 1;
    const lat = Math.asin(y / r) * RAD_TO_DEG;
    const lon = Math.atan2(-z, x) * RAD_TO_DEG;
    return {
        lat: clamp(lat, -90, 90),
        lon: normalizeLongitude(lon),
    };
}

function greatCirclePoint(start, end, t = 0.5, radius = 100) {
    const tt = clamp(Number(t) || 0, 0, 1);
    const a = latLonToVector3(start?.lat, start?.lon, 1);
    const b = latLonToVector3(end?.lat, end?.lon, 1);
    const dot = clamp((a.x * b.x) + (a.y * b.y) + (a.z * b.z), -1, 1);
    const theta = Math.acos(dot);
    if (theta < 1e-6) {
        return latLonToVector3(start?.lat, start?.lon, radius);
    }
    const sinTheta = Math.sin(theta);
    const w1 = Math.sin((1 - tt) * theta) / sinTheta;
    const w2 = Math.sin(tt * theta) / sinTheta;
    const x = ((a.x * w1) + (b.x * w2)) * radius;
    const y = ((a.y * w1) + (b.y * w2)) * radius;
    const z = ((a.z * w1) + (b.z * w2)) * radius;
    return { x, y, z };
}

export {
    clamp,
    normalizeLongitude,
    latLonToVector3,
    vector3ToLatLon,
    greatCirclePoint,
};
