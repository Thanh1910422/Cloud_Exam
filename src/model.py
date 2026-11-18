import tensorflow as tf

import keras

from keras import layers

from src.config import (
    BACKBONE,
    IMAGE_SIZE,
    LEARNING_RATE_STAGE1,
    LEARNING_RATE_STAGE2,
    WEIGHT_DECAY_STAGE2,
    FINE_TUNE_LAST_LAYERS,
    LABEL_SMOOTHING,
)


def get_backbone(input_shape, backbone=BACKBONE):
    """
    Tra ve (base_model, ham_preprocess).

    EfficientNetV2 da tich hop san buoc chuan hoa (include_preprocessing=True),
    nhan dau vao pixel [0, 255] -> khop voi data_loader.
    """

    if backbone == "efficientnetv2b0":
        base = keras.applications.EfficientNetV2B0(
            input_shape=input_shape,
            include_top=False,
            weights="imagenet",
            include_preprocessing=True,
        )
        return base, None

    if backbone == "efficientnetv2b2":
        base = keras.applications.EfficientNetV2B2(
            input_shape=input_shape,
            include_top=False,
            weights="imagenet",
            include_preprocessing=True,
        )
        return base, None

    if backbone == "mobilenetv2":
        base = keras.applications.MobileNetV2(
            input_shape=input_shape,
            include_top=False,
            weights="imagenet",
        )
        return base, keras.applications.mobilenet_v2.preprocess_input

    raise ValueError(f"Backbone khong ho tro: {backbone}")


def build_augmentation():
    """
    Tang cuong du lieu online (chi hoat dong khi training=True).
    La lua chup o nhieu goc / anh sang khac nhau -> them dich chuyen
    va do sang so voi ban cu.
    """

    return keras.Sequential(
        [
            layers.RandomFlip("horizontal_and_vertical"),
            layers.RandomRotation(0.15, fill_mode="reflect"),
            layers.RandomZoom((-0.2, 0.1), fill_mode="reflect"),
            layers.RandomTranslation(0.1, 0.1, fill_mode="reflect"),
            layers.RandomBrightness(0.15, value_range=(0, 255)),
            layers.RandomContrast(0.15),
        ],
        name="augmentation",
    )


def build_model(num_classes, image_size=IMAGE_SIZE, backbone=BACKBONE):
    """
    Xay dung mo hinh Transfer Learning (mac dinh EfficientNetV2-B0).
    """

    # Chuan hoa kich thuoc anh
    if isinstance(image_size, int):
        input_shape = (image_size, image_size, 3)
    else:
        input_shape = (image_size[0], image_size[1], 3)

    inputs = keras.Input(
        shape=input_shape,
        dtype=tf.float32,
        name="input_image"
    )

    # 1. Tang cuong du lieu anh
    x = build_augmentation()(inputs)

    # 2. Backbone + chuan hoa anh
    base_model, preprocess = get_backbone(input_shape, backbone)

    if preprocess is not None:
        x = preprocess(x)

    # Dong bang backbone o giai doan 1
    base_model.trainable = False

    # training=False: BatchNorm cua backbone luon o che do suy luan,
    # ke ca khi fine-tuning (quan trong voi tap du lieu nho).
    x = base_model(x, training=False)

    # 3. Classification head gon hon
    # Ban cu: BN + Dropout 0.35 + Dense 256 + Dropout 0.30 -> regularize qua
    # manh voi ~600 anh, mo hinh bi underfit (train acc chi ~88%).
    x = layers.GlobalAveragePooling2D(name="gap")(x)
    x = layers.Dropout(0.3, name="head_dropout")(x)

    outputs = layers.Dense(
        num_classes,
        activation="softmax",
        dtype="float32",
        name="predictions"
    )(x)

    model = keras.Model(
        inputs=inputs,
        outputs=outputs,
        name=f"Rice_Leaf_{backbone}"
    )

    return model, base_model


def make_loss():
    # Nhan dang one-hot (data_loader) -> dung duoc label smoothing
    return keras.losses.CategoricalCrossentropy(
        label_smoothing=LABEL_SMOOTHING
    )


def compile_stage1(model):
    """
    Compile mo hinh cho giai doan 1:
    Chi huan luyen lop phan loai.
    """

    model.compile(
        optimizer=keras.optimizers.Adam(
            learning_rate=LEARNING_RATE_STAGE1
        ),
        loss=make_loss(),
        metrics=["accuracy"]
    )

    return model


def find_backbone(model):
    """Tim backbone (mot keras.Model long ben trong) - khong phu thuoc ten."""

    for layer in model.layers:
        if isinstance(layer, keras.Model) and layer.name != "augmentation":
            return layer

    raise ValueError("Khong tim thay backbone trong mo hinh.")


def unfreeze_model(model, fine_tune_last_layers=FINE_TUNE_LAST_LAYERS):
    """
    Mo bang cac lop cuoi cua backbone de fine-tuning o giai doan 2.
    BatchNorm van duoc dong bang.
    """

    base_model = find_backbone(model)
    base_model.trainable = True

    if fine_tune_last_layers is None:
        start = 0
    else:
        start = max(0, len(base_model.layers) - fine_tune_last_layers)

    for index, layer in enumerate(base_model.layers):
        layer.trainable = (
            index >= start
            and not isinstance(layer, layers.BatchNormalization)
        )

    model.compile(
        optimizer=keras.optimizers.AdamW(
            learning_rate=LEARNING_RATE_STAGE2,
            weight_decay=WEIGHT_DECAY_STAGE2,
        ),
        loss=make_loss(),
        metrics=["accuracy"]
    )

    return model


if __name__ == "__main__":

    print("=" * 60)
    print(f"XAY DUNG MO HINH {BACKBONE.upper()}")
    print("=" * 60)

    model, base_model = build_model(num_classes=6)
    compile_stage1(model)
    model.summary()

    total_params = model.count_params()
    trainable_params = sum(
        int(tf.size(variable).numpy())
        for variable in model.trainable_variables
    )

    print("\nTONG SO THAM SO:", total_params)
    print("THAM SO CO THE HUAN LUYEN:", trainable_params)
    print("THAM SO KHONG HUAN LUYEN:", total_params - trainable_params)
    print("\nKHOI TAO MO HINH THANH CONG!")
