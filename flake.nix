{
  description = "sudoplz - case-by-case sudo access for AI coding agents via GUI approval";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        runtimeDeps = with pkgs; [
          age
          zenity
          openssl
          openssh
          procps
        ] ++ pkgs.lib.optionals pkgs.stdenv.isDarwin [
          # osascript ships with macOS itself
        ];

        sudoplz = pkgs.python3Packages.buildPythonApplication {
          pname = "sudoplz";
          version = "0.3.0";
          pyproject = true;

          src = ./.;

          build-system = with pkgs.python3Packages; [ hatchling ];

          dependencies = with pkgs.python3Packages; [ keyring ];

          nativeBuildInputs = [ pkgs.makeWrapper ];

          postFixup = ''
            for prog in $out/bin/askpass $out/bin/sudoplz; do
              wrapProgram "$prog" --prefix PATH : ${pkgs.lib.makeBinPath runtimeDeps}
            done
          '';

          pythonImportsCheck = [ "sudoplz" ];
        };
      in
      {
        packages.default = sudoplz;
        packages.sudoplz = sudoplz;

        apps.default = flake-utils.lib.mkApp {
          drv = sudoplz;
          exePath = "/bin/sudoplz";
        };
        apps.sudoplz = flake-utils.lib.mkApp {
          drv = sudoplz;
          exePath = "/bin/sudoplz";
        };
        apps.askpass = flake-utils.lib.mkApp {
          drv = sudoplz;
          exePath = "/bin/askpass";
        };

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.uv sudoplz ] ++ runtimeDeps;
        };
      });
}
