# Product Types

`product_types` describes logical domains and services exposed by a configured
product. A project profile selects an adapter with `product_type`. Capabilities
are evaluated from the enabled component builders in the effective Moulin
manifest, so changing parameters can change the available services without
changing the product type.

The built-in `gen5_xen_android` adapter treats every enabled component whose
builder type is `android` as an Android domain. It exposes
`product.android-adb` when at least one such component exists. It does not
depend on component names or product-specific parameter names.

Board types remain responsible for physical lifecycle operations. Product
types must not implement board power control or flashing. The GEN5 Android ADB
resolver uses the concrete board's serial console to enter DomD through
`xl console DomD` and read its current DHCP address. A configured static ADB
serial still takes precedence in the CTS/VTS profile; MAC and board-IP lookup
remain fallback paths when no serial console is configured.
