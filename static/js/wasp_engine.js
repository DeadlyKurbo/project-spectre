const container = document.getElementById("map-container");

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    1000
);

camera.position.z = 120;

const renderer = new THREE.WebGLRenderer({ antialias: true });

renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);

container.appendChild(renderer.domElement);



/* GRID */

const grid = new THREE.GridHelper(
    500,
    50,
    0x00ffff,
    0x004444
);

scene.add(grid);



/* TEST OBJECT (marker prototype) */

const geometry = new THREE.SphereGeometry(1.5, 16, 16);

const material = new THREE.MeshBasicMaterial({
    color: 0xff0040
});

const marker = new THREE.Mesh(geometry, material);

marker.position.set(0, 2, 0);

scene.add(marker);



/* ANIMATION LOOP */

function animate() {

    requestAnimationFrame(animate);

    marker.rotation.y += 0.01;

    renderer.render(scene, camera);
}

animate();



/* RESIZE HANDLER */

window.addEventListener("resize", () => {

    camera.aspect = window.innerWidth / window.innerHeight;

    camera.updateProjectionMatrix();

    renderer.setSize(window.innerWidth, window.innerHeight);

});
