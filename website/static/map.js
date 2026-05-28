const map = new maplibregl.Map({
    style: 'https://tiles.openfreemap.org/styles/liberty',
    center: [12.563517, 55.680466],
    zoom: 11.3,
    container: 'map',
})

const marker = new maplibregl.Marker()
  .setLngLat([12.5585918, 55.7019809])
  .setPopup(
    new maplibregl.Popup().setText("Caféen?")
  )
  .addTo(map);

async function loadVenues() {
    const response = await fetch("/auto_query");
    const data = await response.json();

    data.forEach(venue => {
        const marker = new maplibregl.Marker()
            .setLngLat([venue.lon, venue.lat])
            .setPopup(
                new maplibregl.Popup().setText(venue.name)
            )
            .addTo(map)
    });
}

window.addEventListener("load", loadVenues);