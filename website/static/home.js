async function searchVenues() {
    const query = document.getElementById("searchInput").value;

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

