function updateUrl(query) {
    const url = new URL(window.location);

    url.searchParams.set("search", query);

    window.history.replaceState({}, "", url);
}

async function searchVenues() {
    const query = document.getElementById("searchInput").value.trim();

    updateUrl(query)

    const response = await fetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query })
    });

    const data = await response.json();

    const resultsDiv = document.getElementById("results");

    if (!data.length) {
        resultsDiv.innerHTML = `
            <div class='search-result'>
                <p>Ingen resultater fundet.</p>
            </div>
        `;
        return;
    }

    resultsDiv.innerHTML = data
        .map(item => `
            <div class='search-result'>
                <a href='${item.google_maps_uri}' target="_blank" rel="noopener noreferrer">
                    <p class='search-result-name'>${item.name}</p>
                </a>
                <p class='search-result-address'>${item.address}</p>
                <p class='google-maps-rating'>
                    Google rating: ${item.google_rating} (${item.google_user_rating_count})
                </p>
            </div>
        `)
        .join('');
}

document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("searchInput");

    if (window.INITIAL_QUERY) {
        input.value = (window.INITIAL_QUERY);
        searchVenues();
    }

    const form = document.getElementById("searchForm");

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        searchVenues();
    });
});
