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
        resultsDiv.innerHTML = "<p>No results found</p>";
        return;
    }

    resultsDiv.innerHTML = data
        .map(item => `<p>${item.name}, ${item.address}</p>`)
        .join("");
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