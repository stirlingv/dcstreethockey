document.addEventListener("DOMContentLoaded", function() {
    const bannerContent = document.querySelector(".banner-content");
    const bannerLogo = document.querySelector(".banner-logo");

    function adjustLogoSize() {
        const contentHeight = bannerContent.offsetHeight;
        bannerLogo.style.maxHeight = `${contentHeight}px`;
    }

    adjustLogoSize();
    window.addEventListener("resize", adjustLogoSize);
});