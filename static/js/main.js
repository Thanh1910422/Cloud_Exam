document.addEventListener("DOMContentLoaded", function () {
    console.log("HSK Exam loaded successfully!");

    const levelCards = document.querySelectorAll(".level-card");

    levelCards.forEach(function (card) {
        card.addEventListener("mouseenter", function () {
            card.style.cursor = "pointer";
        });
    });
});