// ============================================================
// ABC BUSINESS MANAGER - SERVICE WORKER
// Catálogo offline seguro
// ============================================================
//
// NO cachea:
// - login
// - POST
// - pedidos
// - compras
// - inventario
// - producción
// - finanzas
// - configuración
//
// Solo guarda recursos estáticos y la última versión visitada
// del catálogo.
// ============================================================


const CACHE_STATIC = "abc-static-v2";
const CACHE_CATALOGO = "abc-catalogo-v2";


const STATIC_ASSETS = [
    "/static/manifest.json",
    "/static/icons/favicon-64.png",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/uploads/logo_abc.png"
];


// ============================================================
// INSTALACIÓN
// ============================================================

self.addEventListener(
    "install",
    function (event) {

        event.waitUntil(
            caches
                .open(CACHE_STATIC)
                .then(function (cache) {

                    return cache.addAll(
                        STATIC_ASSETS
                    );

                })
        );

        self.skipWaiting();

    }
);


// ============================================================
// ACTIVACIÓN
// ============================================================

self.addEventListener(
    "activate",
    function (event) {

        const permitidos = [
            CACHE_STATIC,
            CACHE_CATALOGO
        ];

        event.waitUntil(
            caches
                .keys()
                .then(function (keys) {

                    return Promise.all(

                        keys.map(
                            function (key) {

                                if (
                                    !permitidos.includes(
                                        key
                                    )
                                ) {

                                    return caches.delete(
                                        key
                                    );

                                }

                            }
                        )

                    );

                })
                .then(function () {

                    return self.clients.claim();

                })
        );

    }
);


// ============================================================
// INTERCEPTAR SOLICITUDES
// ============================================================

self.addEventListener(
    "fetch",
    function (event) {

        const request = event.request;


        // ----------------------------------------------------
        // NUNCA INTERVENIR EN POST, PUT, DELETE, ETC.
        // ----------------------------------------------------

        if (request.method !== "GET") {
            return;
        }


        const url = new URL(
            request.url
        );


        // ----------------------------------------------------
        // SOLO TRABAJAR CON ABC
        // ----------------------------------------------------

        if (
            url.origin
            !== self.location.origin
        ) {
            return;
        }


        // ====================================================
        // RECURSOS ESTÁTICOS
        // ====================================================

        if (
            url.pathname.startsWith(
                "/static/"
            )
        ) {

            event.respondWith(

                caches
                    .match(request)
                    .then(function (cached) {

                        // Si ya existe guardado,
                        // utilizarlo.

                        if (cached) {

                            return cached;

                        }


                        // Si no existe,
                        // descargarlo normalmente.

                        return fetch(request)
                            .then(
                                function (response) {

                                    if (
                                        !response
                                        || !response.ok
                                    ) {

                                        return response;

                                    }


                                    const copia =
                                        response.clone();


                                    caches
                                        .open(
                                            CACHE_STATIC
                                        )
                                        .then(
                                            function (cache) {

                                                cache.put(
                                                    request,
                                                    copia
                                                );

                                            }
                                        );


                                    return response;

                                }
                            );

                    })

            );


            return;

        }


        // ====================================================
        // CATÁLOGO
        // ====================================================
        //
        // NETWORK FIRST
        //
        // CON INTERNET:
        // Obtiene el catálogo actualizado de ABC y guarda
        // una copia.
        //
        // SIN INTERNET:
        // Utiliza la última copia guardada.
        //
        // ====================================================

        if (
            url.pathname === "/catalogo/"
            || url.pathname === "/catalogo"
        ) {

            event.respondWith(

                fetch(request)

                    // ----------------------------------------
                    // HAY INTERNET
                    // ----------------------------------------

                    .then(
                        function (response) {

                            // Solo guardar una página real
                            // del catálogo.
                            //
                            // Esto evita guardar por accidente
                            // una redirección hacia el login.

                            if (
                                response.ok
                                && !response.redirected
                                && response.type === "basic"
                            ) {

                                const copia =
                                    response.clone();


                                caches
                                    .open(
                                        CACHE_CATALOGO
                                    )
                                    .then(
                                        function (cache) {

                                            // Guardamos siempre una copia
                                            // con esta dirección estándar.
                                            //
                                            // Así tendremos disponible
                                            // el catálogo completo offline.

                                            cache.put(
                                                "/catalogo/",
                                                copia
                                            );

                                        }
                                    );

                            }


                            return response;

                        }
                    )


                    // ----------------------------------------
                    // NO HAY INTERNET
                    // ----------------------------------------

                    .catch(
                        function () {

                            return caches
                                .open(
                                    CACHE_CATALOGO
                                )
                                .then(
                                    function (cache) {

                                        return cache.match(
                                            "/catalogo/"
                                        );

                                    }
                                )
                                .then(
                                    function (cached) {

                                        // Si ya visitaste el catálogo
                                        // anteriormente, mostrar la copia.

                                        if (cached) {

                                            return cached;

                                        }


                                        // Si nunca se abrió el catálogo
                                        // con Internet en este dispositivo,
                                        // todavía no existe copia.

                                        return new Response(

                                            `
                                            <!doctype html>

                                            <html lang="es">

                                            <head>

                                                <meta charset="utf-8">

                                                <meta
                                                    name="viewport"
                                                    content="width=device-width, initial-scale=1"
                                                >

                                                <title>
                                                    ABC sin conexión
                                                </title>

                                            </head>


                                            <body
                                                style="
                                                    font-family: Arial, sans-serif;
                                                    padding: 30px;
                                                    background: #f5f7fb;
                                                    color: #13255b;
                                                "
                                            >

                                                <div
                                                    style="
                                                        max-width: 500px;
                                                        margin: 50px auto;
                                                        padding: 25px;
                                                        background: white;
                                                        border-radius: 12px;
                                                        box-shadow: 0 5px 20px rgba(0,0,0,.08);
                                                    "
                                                >

                                                    <h2>
                                                        Catálogo todavía no disponible offline
                                                    </h2>

                                                    <p>
                                                        Conéctate a Internet,
                                                        inicia sesión y abre
                                                        el Catálogo una vez.
                                                    </p>

                                                    <p>
                                                        Después quedará guardado
                                                        para consultarlo sin
                                                        conexión.
                                                    </p>

                                                </div>

                                            </body>

                                            </html>
                                            `,

                                            {
                                                headers: {

                                                    "Content-Type":
                                                        "text/html; charset=utf-8"

                                                }
                                            }

                                        );

                                    }
                                );

                        }
                    )

            );

        }

    }
);