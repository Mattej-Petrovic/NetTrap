const map = L.map("map", {
    zoomControl: true,
    preferCanvas: false,
}).setView([20, 0], 2);

const baseLayers = [
    {
        name: "openstreetmap",
        url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        options: {
            attribution: "&copy; OpenStreetMap contributors",
            maxZoom: 19,
            crossOrigin: true,
        },
    },
    {
        name: "carto_dark",
        url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        options: {
            attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
            subdomains: "abcd",
            maxZoom: 19,
            crossOrigin: true,
        },
    },
];

const basemapStatus = {
    provider: null,
    providerIndex: -1,
    basemapReady: false,
    basemapFailed: false,
    tileLoads: 0,
    tileErrors: 0,
    fallbackCount: 0,
    lastTileUrl: "",
    lastError: "",
    switchReason: "",
    attemptedProviders: [],
};

window.nettrapMapStatus = basemapStatus;
window.getNetTrapMapStatus = () => JSON.stringify(basemapStatus);

let activeBaseLayer = null;
let basemapFallbackTimer = null;
let basemapFallbackTriggered = false;
let activeBasemapToken = 0;

function clearBasemapFallbackTimer() {
    if (basemapFallbackTimer !== null) {
        clearTimeout(basemapFallbackTimer);
        basemapFallbackTimer = null;
    }
}

function updateBasemapStatus(patch) {
    Object.assign(basemapStatus, patch);
}

function switchBasemap(index, reason) {
    if (index >= baseLayers.length) {
        clearBasemapFallbackTimer();
        updateBasemapStatus({
            basemapFailed: true,
            switchReason: reason,
            lastError: basemapStatus.lastError || "all basemap providers failed",
        });
        return;
    }

    const provider = baseLayers[index];
    clearBasemapFallbackTimer();
    basemapFallbackTriggered = false;
    activeBasemapToken += 1;
    const basemapToken = activeBasemapToken;

    if (activeBaseLayer) {
        map.removeLayer(activeBaseLayer);
        activeBaseLayer = null;
    }

    updateBasemapStatus({
        provider: provider.name,
        providerIndex: index,
        basemapReady: false,
        basemapFailed: false,
        tileLoads: 0,
        tileErrors: 0,
        lastTileUrl: "",
        lastError: "",
        switchReason: reason,
    });

    if (!basemapStatus.attemptedProviders.includes(provider.name)) {
        basemapStatus.attemptedProviders.push(provider.name);
    }

    activeBaseLayer = L.tileLayer(provider.url, provider.options);
    activeBaseLayer.on("tileload", (event) => {
        if (basemapToken !== activeBasemapToken) {
            return;
        }
        const src = event.tile?.currentSrc || event.tile?.src || basemapStatus.lastTileUrl;
        updateBasemapStatus({
            basemapReady: true,
            lastTileUrl: src,
        });
        basemapStatus.tileLoads += 1;
        clearBasemapFallbackTimer();
    });
    activeBaseLayer.on("tileerror", (event) => {
        if (basemapToken !== activeBasemapToken) {
            return;
        }
        const src = event.tile?.currentSrc || event.tile?.src || basemapStatus.lastTileUrl;
        basemapStatus.tileErrors += 1;
        updateBasemapStatus({
            lastTileUrl: src,
            lastError: `tileerror:${provider.name}`,
        });
        if (!basemapStatus.basemapReady && !basemapFallbackTriggered) {
            basemapFallbackTriggered = true;
            basemapStatus.fallbackCount += 1;
            switchBasemap(index + 1, `tileerror:${provider.name}`);
        }
    });
    activeBaseLayer.addTo(map);

    basemapFallbackTimer = setTimeout(() => {
        if (!basemapStatus.basemapReady && !basemapFallbackTriggered) {
            basemapFallbackTriggered = true;
            basemapStatus.fallbackCount += 1;
            switchBasemap(index + 1, `timeout:${provider.name}`);
        }
    }, 3500);
}

switchBasemap(0, "initial");

const markerLayer = L.layerGroup().addTo(map);
const markers = {};

function popupHtml(ip, country, city, sessionCount, lastSeen) {
    return `
        <div>
            <div><span class="popup-label">IP:</span>${ip}</div>
            <div><span class="popup-label">Country:</span>${country || "Unknown"}</div>
            <div><span class="popup-label">City:</span>${city || "Unknown"}</div>
            <div><span class="popup-label">Sessions:</span>${sessionCount}</div>
            <div><span class="popup-label">Last seen:</span>${lastSeen}</div>
        </div>
    `;
}

function addMarker(ip, lat, lng, country, city, sessionCount, lastSeen) {
    const radius = 6 + Math.min(sessionCount, 14);
    const popup = popupHtml(ip, country, city, sessionCount, lastSeen);

    if (markers[ip]) {
        markers[ip].setLatLng([lat, lng]);
        markers[ip].setRadius(radius);
        markers[ip].setPopupContent(popup);
        markers[ip].sessionCount = sessionCount;
        markers[ip].lastSeen = lastSeen;
        return;
    }

    const marker = L.circleMarker([lat, lng], {
        color: "#00D4AA",
        fillColor: "#00D4AA",
        fillOpacity: 0.7,
        radius: radius,
        weight: 2,
    });
    marker.bindPopup(popup);
    marker.addTo(markerLayer);
    marker.sessionCount = sessionCount;
    marker.lastSeen = lastSeen;
    markers[ip] = marker;
}

function pulseMarker(ip) {
    const marker = markers[ip];
    if (!marker || !marker._path) {
        return;
    }
    marker._path.classList.remove("marker-pulse");
    void marker._path.offsetWidth;
    marker._path.classList.add("marker-pulse");
    setTimeout(() => {
        if (marker._path) {
            marker._path.classList.remove("marker-pulse");
        }
    }, 1000);
}

function clearMarkers() {
    markerLayer.clearLayers();
    for (const key of Object.keys(markers)) {
        delete markers[key];
    }
}

function fitBounds() {
    const markerItems = Object.values(markers);
    if (markerItems.length === 0) {
        map.setView([20, 0], 2);
        return;
    }
    const group = L.featureGroup(markerItems);
    map.fitBounds(group.getBounds().pad(0.2), { maxZoom: 6 });
}
