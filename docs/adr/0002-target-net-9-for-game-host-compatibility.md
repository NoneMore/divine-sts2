# Target .NET 9 for game-host compatibility

The solution targets .NET 9 because the shipped Slay the Spire 2 process that loads FullAppBridge declares `net9.0` and bundles Microsoft.NETCore.App 9.0.7. A locally installed .NET 10 SDK is therefore not sufficient reason to retarget the repository: a `net10.0` mod could compile but would not satisfy the game's embedded runtime contract. Revisit this constraint when the shipped game host moves to a newer target framework.
