from flask import Blueprint, render_template, request, redirect, url_for
from database import obtener_conexion

variantes_bp = Blueprint(
    "variantes",
    __name__,
    url_prefix="/variantes"
)


@variantes_bp.route("/producto/<int:producto_id>")
def listar(producto_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            nombre,
            sku,
            talla,
            color,
            precio,
            costo_base,
            activo
        FROM variantes_producto
        WHERE producto_id = %s
        AND activo = 1
        ORDER BY nombre ASC, talla ASC, color ASC
    """, (producto_id,))

    variantes = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            nombre
        FROM productos
        WHERE id = %s
        AND activo = 1
    """, (producto_id,))

    producto = cursor.fetchone()

    cursor.close()
    conexion.close()

    if not producto:
        return "Producto no encontrado", 404

    return render_template(
        "variantes/lista.html",
        producto=producto,
        variantes=variantes
    )


@variantes_bp.route("/producto/<int:producto_id>/nuevo", methods=["GET", "POST"])
def nuevo(producto_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            nombre
        FROM productos
        WHERE id = %s
        AND activo = 1
    """, (producto_id,))

    producto = cursor.fetchone()

    if not producto:
        cursor.close()
        conexion.close()
        return "Producto no encontrado", 404

    if request.method == "POST":

        sku = request.form.get("sku", "").strip() or None
        nombre = request.form.get("nombre", "").strip() or None
        talla = request.form.get("talla", "").strip() or None
        color = request.form.get("color", "").strip() or None

        precio = request.form.get("precio") or None
        costo_base = request.form.get("costo_base") or None

        cursor.execute("""
            INSERT INTO variantes_producto
            (
                producto_id,
                sku,
                nombre,
                talla,
                color,
                precio,
                costo_base
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            producto_id,
            sku,
            nombre,
            talla,
            color,
            precio,
            costo_base
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(
            url_for(
                "variantes.listar",
                producto_id=producto_id
            )
        )

    cursor.close()
    conexion.close()

    return render_template(
        "variantes/nuevo.html",
        producto=producto
    )


@variantes_bp.route("/<int:variante_id>/editar", methods=["GET", "POST"])
def editar(variante_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            v.id,
            v.producto_id,
            v.sku,
            v.nombre,
            v.talla,
            v.color,
            v.precio,
            v.costo_base,
            p.nombre AS producto
        FROM variantes_producto v
        INNER JOIN productos p
            ON v.producto_id = p.id
        WHERE v.id = %s
    """, (variante_id,))

    variante = cursor.fetchone()

    if not variante:
        cursor.close()
        conexion.close()
        return "Variante no encontrada", 404

    if request.method == "POST":

        sku = request.form.get("sku", "").strip() or None
        nombre = request.form.get("nombre", "").strip() or None
        talla = request.form.get("talla", "").strip() or None
        color = request.form.get("color", "").strip() or None

        precio = request.form.get("precio") or None
        costo_base = request.form.get("costo_base") or None

        cursor.execute("""
            UPDATE variantes_producto
            SET
                sku = %s,
                nombre = %s,
                talla = %s,
                color = %s,
                precio = %s,
                costo_base = %s
            WHERE id = %s
        """, (
            sku,
            nombre,
            talla,
            color,
            precio,
            costo_base,
            variante_id
        ))

        conexion.commit()

        producto_id = variante["producto_id"]

        cursor.close()
        conexion.close()

        return redirect(
            url_for(
                "variantes.listar",
                producto_id=producto_id
            )
        )

    cursor.close()
    conexion.close()

    return render_template(
        "variantes/editar.html",
        variante=variante
    )


@variantes_bp.route("/<int:variante_id>/desactivar", methods=["POST"])
def desactivar(variante_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT producto_id
        FROM variantes_producto
        WHERE id = %s
    """, (variante_id,))

    variante = cursor.fetchone()

    if not variante:
        cursor.close()
        conexion.close()
        return "Variante no encontrada", 404

    producto_id = variante["producto_id"]

    cursor.execute("""
        UPDATE variantes_producto
        SET activo = 0
        WHERE id = %s
    """, (variante_id,))

    conexion.commit()

    cursor.close()
    conexion.close()

    return redirect(
        url_for(
            "variantes.listar",
            producto_id=producto_id
        )
    )