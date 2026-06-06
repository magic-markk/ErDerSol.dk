
const map = new maplibregl.Map({
    style: 'https://tiles.openfreemap.org/styles/liberty',
    center: [12.563517, 55.680466],
    zoom: 11.3,
    container: 'map',
});

let userLocationMarker = null;

function formatDistance(meters) {
    if (meters === null || meters === undefined) {
        return "-";
    }

    if (meters >= 1000) {
        return `${(meters / 1000).toFixed(1)} km`;
    }

    return `${Math.round(meters)} m`;
}

function formatValue(value, suffix = "") {
    if (value === null || value === undefined || value === "") {
        return "-";
    }

    return `${value}${suffix}`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderNearbyBars(bars) {
    const resultsDiv = document.getElementById("results");

    if (!resultsDiv) {
        return;
    }

    if (!bars.length) {
        resultsDiv.innerHTML = `
            <div class="search-result">
                <p>No nearby bars found</p>
            </div>
        `;
        return;
    }

    resultsDiv.innerHTML = bars
        .map((bar, index) => {
            const mapLink = bar.google_maps_uri || `https://www.google.com/maps/search/?api=1&query=${bar.lat},${bar.lon}`;

            return `
                <div class="search-result nearby-result">
                    <a href="${escapeHtml(mapLink)}" target="_blank" rel="noopener noreferrer">
                        <p class="search-result-name">${index + 1}. ${escapeHtml(bar.name || "Unnamed venue")}</p>
                    </a>
                    <p class="search-result-address">${escapeHtml(bar.address || "")}</p>
                    <p class="nearby-score">
                        Score: ${formatValue(bar.total_score)}/${formatValue(bar.score_max)}
                    </p>
                    <p>Distance: ${formatDistance(bar.distance_m)}</p>
                    <p>
                        Weather: ${formatValue(bar.air_temperature, " C")},
                        wind ${formatValue(bar.wind_speed, " m/s")},
                        clouds ${formatValue(bar.cloud_area_fraction, "%")}
                    </p>
                    <p class="google-maps-rating">
                        Google Rating: ${formatValue(bar.google_rating)}
                        (${formatValue(bar.google_user_rating_count)})
                    </p>
                    <p class="score-reasons">${escapeHtml(bar.score_reasons || "")}</p>
                </div>
            `;
        })
        .join("");
}

async function loadNearbyBars(lat, lon) {
    const resultsDiv = document.getElementById("results");

    if (resultsDiv) {
        resultsDiv.innerHTML = `
            <div class="search-result">
                <p>Finding the best nearby sunny spots...</p>
            </div>
        `;
    }

    const response = await fetch("/nearby_bars", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat, lon })
    });

    if (!response.ok) {
        throw new Error("Could not load nearby bars.");
    }

    const bars = await response.json();
    renderNearbyBars(bars);
}

// Hardcoded marker for Caféen
const cafeenMarker = new maplibregl.Marker()
    .setLngLat([12.5585918, 55.7019809])
    .setPopup(
        new maplibregl.Popup()
            .setHTML(`
                <strong>Caféen?</strong>
                <br>Universitetsparken 15C, 2100 København
            `)
    )
    .addTo(map);



async function loadVenues() {
    const response = await fetch("/auto_query");
    const data = await response.json();

    const geojson = {
        type: "FeatureCollection",
        features: data
            .filter(venue => venue.lat && venue.lon)
            .map(venue => ({
                type: "Feature",
                geometry: {
                    type: "Point",
                    coordinates: [
                        Number(venue.lon),
                        Number(venue.lat)
                    ]
                },
                properties: {
                    name: venue.name,
                    address: venue.address,
                    cloud_area: venue.cloud_area
                }
            }))
    };

    map.addSource("venues", {
        type: "geojson",
        data: geojson,
        cluster: true,
        clusterMaxZoom: 14,
        clusterRadius: 50
    });

    map.addLayer({
        id: "clusters",
        type: "circle",
        source: "venues",
        filter: ["has", "point_count"],
        paint: {
            "circle-color": [
                "step",
                ["get", "point_count"],
                "#51bbd6",
                10,
                "#f1f075",
                30,
                "#f28cb1"
            ],
            "circle-radius": [
                "step",
                ["get", "point_count"],
                18,
                10,
                24,
                30,
                32
            ]
        }
    });

    map.addLayer({
        id: "cluster-count",
        type: "symbol",
        source: "venues",
        filter: ["has", "point_count"],
        layout: {
            "text-field": "{point_count_abbreviated}",
            "text-size": 12
        }
    });

    map.addLayer({
        id: "unclustered-venues",
        type: "circle",
        source: "venues",
        filter: ["!", ["has", "point_count"]],
        paint: {
            "circle-color": "#11b4da",
            "circle-radius": 7,
            "circle-stroke-width": 1,
            "circle-stroke-color": "#ffffff"
        }
    });

    map.on("click", "clusters", async (event) => {
        const features = map.queryRenderedFeatures(event.point, {
            layers: ["clusters"]
        });

        const clusterId = features[0].properties.cluster_id;
        const zoom = await map
            .getSource("venues")
            .getClusterExpansionZoom(clusterId);

        map.easeTo({
            center: features[0].geometry.coordinates,
            zoom: zoom
        });
    });

    map.on("click", "unclustered-venues", (event) => {
        const coordinates = event.features[0].geometry.coordinates.slice();
        const name = event.features[0].properties.name;
        const address = event.features[0].properties.address;
        const cloud_area = event.features[0].properties.cloud_area;

        new maplibregl.Popup()
            .setLngLat(coordinates)
            .setHTML(`<strong>${name}</strong><br>${address}, ${cloud_area}`)
            .addTo(map);
    });

    map.on("mouseenter", "clusters", () => {
        map.getCanvas().style.cursor = "pointer";
    });

    map.on("mouseleave", "clusters", () => {
        map.getCanvas().style.cursor = "";
    });

    map.on("mouseenter", "unclustered-venues", () => {
        map.getCanvas().style.cursor = "pointer";
    });

    map.on("mouseleave", "unclustered-venues", () => {
        map.getCanvas().style.cursor = "";
    });
}

function useMyLocation() {
    if (!navigator.geolocation) {
        alert("Your browser does not support geolocation.");
        return;
    }

    navigator.geolocation.getCurrentPosition(
        async (position) => {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;

            map.flyTo({
                center: [lon, lat],
                zoom: 15
            });

            if (userLocationMarker) {
                userLocationMarker.remove();
            }

            userLocationMarker = new maplibregl.Marker({
                color: '#F06516'
            })
                .setLngLat([lon, lat])
                .setPopup(
                    new maplibregl.Popup().setText("You are here")
                )
                .addTo(map);

            try {
                await loadNearbyBars(lat, lon);
            } catch (error) {
                console.error(error);
                const resultsDiv = document.getElementById("results");

                if (resultsDiv) {
                    resultsDiv.innerHTML = `
                        <div class="search-result">
                            <p>Could not load nearby bars.</p>
                        </div>
                    `;
                }
            }
        },
        (error) => {
            console.error(error);
            alert("Could not get your location.");
        },
        {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 60000
        }
    );
}

map.on("load", loadVenues);
