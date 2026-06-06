
const map = new maplibregl.Map({
    style: 'https://tiles.openfreemap.org/styles/liberty',
    center: [12.563517, 55.680466],
    zoom: 11.3,
    container: 'map',
});

let userLocationMarker = null;

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
        (position) => {
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
