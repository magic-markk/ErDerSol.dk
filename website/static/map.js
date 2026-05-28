const map = new maplibregl.Map({
    style: 'https://tiles.openfreemap.org/styles/liberty',
    center: [12.563517, 55.680466],
    zoom: 11.3,
    container: 'map',
});

let userLocationMarker = null;

const hjem = new maplibregl.Marker({
    color: '#0b1983'
})
    .setLngLat([12.5585918, 55.7019809])
    .setPopup(
        new maplibregl.Popup().setText("Caféen?\n Dit nye hjem")
    )
    .addTo(map);

async function loadVenues() {
    const response = await fetch("/auto_query");
    const data = await response.json();

    data.forEach(venue => {
        if (venue.name == 'Caféen?') {
            return
        }
        new maplibregl.Marker()
            .setLngLat([venue.lon, venue.lat])
            .setPopup(
                new maplibregl.Popup().setText(venue.name)
            )
            .addTo(map);
    });
    console.log(data)
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

window.addEventListener("load", loadVenues);